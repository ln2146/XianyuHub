import asyncio

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_factory
from app.domains.buyer.models import MarketItemRecord, PriceSnapshot, TaskResult
from app.domains.buyer.pipeline import run_task
from app.goofish.gateway import account_key
from app.intelligence.llm import LLMGateway, LLMResult, set_llm
from app.runtime import get_runtime
from tests.test_goofish_protocol import load

TASK = {
    "name": "M1 Air",
    "keywords": ["macbook air m1"],
    "max_price": 4000,
    "rules": {"exclude": ["配件"]},
    "criteria": "必须：M1 芯片；电池 ≥ 85%",
    "cron": "*/30 8-23 * * *",
    "price_drop_percent": 5,
    "enabled": True,
}


class FakeLLM:
    def __init__(self):
        self.calls = []

    async def complete(self, **kw):
        self.calls.append(kw)
        if "keep" in kw["schema"]["properties"]:
            return LLMResult(text='{"keep": true, "reason": "相关"}', model="m")
        return LLMResult(
            text='{"verdict":"recommend","confidence":0.8,"reason":"个人自用，电池 92%","risk_tags":[],'
            '"need_confirm":["发票"],"questions_for_seller":["有发票吗？"],"seller_type":"personal"}',
            model="m",
        )


def mock_market(search_data):
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    respx.post(url__regex=r".*idlemtopsearch\.pc\.search.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": search_data})
    )
    respx.post(url__regex=r".*mtop\.taobao\.idle\.pc\.detail.*").mock(
        return_value=httpx.Response(200, json=load("detail_response.json"))
    )


@respx.mock
async def test_buyer_pipeline_end_to_end(admin_client):
    fake = FakeLLM()
    set_llm(LLMGateway(provider=fake))
    hook = respx.post("https://hook.example.com/n").mock(return_value=httpx.Response(200))
    await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "h", "type": "webhook", "config": {"url": "https://hook.example.com/n"}},
    )
    search = load("search_response.json")["data"]
    search["resultInfo"]["hasNextPage"] = False
    mock_market(search)

    r = await admin_client.post("/api/v1/buyer/tasks", json=TASK)
    assert r.status_code == 201, r.text
    task_id = r.json()["id"]

    stats = await run_task(task_id)
    assert stats.fetched == 2 and stats.new == 2
    # 第二条 1.2 万超出 max_price 4000 → 规则筛除；第一条进入 AI 判定
    assert stats.filtered == 1 and stats.evaluated == 1 and stats.recommended == 1
    assert hook.called
    sent = hook.calls[-1].request.content.decode()
    assert "推荐" in sent and "900000000001" in sent

    results = (await admin_client.get(f"/api/v1/buyer/results?task_id={task_id}")).json()
    assert len(results) == 1 and results[0]["verdict"] == "recommend"
    assert results[0]["questions"] == ["有发票吗？"] and results[0]["item"]["title"]
    # 多模态判定带上了图片
    judge_call = [c for c in fake.calls if "verdict" in c["schema"]["properties"]][0]
    assert len(judge_call["images"]) == 2 and "M1 芯片" in judge_call["messages"][0].content

    all_results = (await admin_client.get(f"/api/v1/buyer/results?task_id={task_id}&verdict=all")).json()
    assert len(all_results) == 2

    # 再跑一次：已处理的商品不会重复判定；价格下降触发降价提醒
    search["resultList"][0]["data"]["item"]["main"]["exContent"]["price"] = [{"text": "¥2900"}]
    mock_market(search)
    hook.calls.reset()
    stats2 = await run_task(task_id)
    assert stats2.new == 0 and stats2.price_drops == 1
    assert "降价" in hook.calls[-1].request.content.decode()
    async with session_factory()() as s:
        snaps = (await s.execute(select(PriceSnapshot).where(PriceSnapshot.item_id == "900000000001"))).scalars().all()
        assert [p.price for p in snaps] == [3200, 2900]
        rec = await s.get(MarketItemRecord, "900000000001")
        assert rec.seller_zhima == "信用极好" and rec.desc

    r = await admin_client.patch(f"/api/v1/buyer/results/{results[0]['id']}", json={"mark": "ignored"})
    assert r.json()["mark"] == "ignored"
    assert (await admin_client.get(f"/api/v1/buyer/results?task_id={task_id}")).json() == []
    csv_resp = await admin_client.get(f"/api/v1/buyer/results/export.csv?task_id={task_id}")
    assert "标题" in csv_resp.text
    set_llm(None)


@respx.mock
async def test_interrupted_candidates_are_judged_on_next_run(admin_client):
    # 上次运行在判定前被打断：结果行停在默认的 filtered、没有原因也没有结论。下次搜到时应补判，而不是永远被当成已处理
    set_llm(LLMGateway(provider=FakeLLM()))
    search = load("search_response.json")["data"]
    search["resultInfo"]["hasNextPage"] = False
    mock_market(search)
    task_id = (await admin_client.post("/api/v1/buyer/tasks", json=TASK)).json()["id"]
    async with session_factory()() as s:
        s.add(TaskResult(task_id=task_id, item_id="900000000001"))
        await s.commit()

    stats = await run_task(task_id)
    assert stats.new == 1  # 只有另一件是新商品；卡住的那件是补判
    assert stats.evaluated == 1 and stats.recommended == 1
    async with session_factory()() as s:
        res = (
            await s.execute(
                select(TaskResult).where(TaskResult.task_id == task_id, TaskResult.item_id == "900000000001")
            )
        ).scalar_one()
        assert res.stage == "evaluated" and res.verdict == "recommend"
    set_llm(None)


class BrokenPrescreenLLM(FakeLLM):
    async def complete(self, **kw):
        if "keep" in kw["schema"]["properties"]:
            self.calls.append(kw)
            return LLMResult(text='{"keep": false, "reason": "电池充不进电、只能插电使', model="m")  # 被截断
        return await super().complete(**kw)


@respx.mock
async def test_broken_prescreen_output_does_not_drop_the_item(admin_client):
    set_llm(LLMGateway(provider=BrokenPrescreenLLM()))
    search = load("search_response.json")["data"]
    search["resultInfo"]["hasNextPage"] = False
    mock_market(search)
    task_id = (await admin_client.post("/api/v1/buyer/tasks", json=TASK)).json()["id"]
    stats = await run_task(task_id)
    # 粗筛输出坏掉时不记成出错，照常进入正式判定
    assert stats.errors == 0 and stats.evaluated == 1 and stats.recommended == 1
    set_llm(None)


@respx.mock
async def test_rule_filtered_items_are_rechecked_after_rules_change(admin_client):
    set_llm(LLMGateway(provider=FakeLLM()))
    search = load("search_response.json")["data"]
    search["resultInfo"]["hasNextPage"] = False
    mock_market(search)
    # 第一次：用标题里的词把第一件筛掉
    title = search["resultList"][0]["data"]["item"]["main"]["exContent"]["title"]
    word = next(w for w in ("macbook", "MacBook", "air", "Air", "M1", "m1") if w in title)
    body = {**TASK, "rules": {"exclude": [word]}}
    task_id = (await admin_client.post("/api/v1/buyer/tasks", json=body)).json()["id"]
    stats = await run_task(task_id)
    assert stats.recommended == 0

    # 用户放宽规则后再跑：已筛除的商品按新规则重查并进入判定，不算作新商品
    body["rules"] = {"exclude": ["配件"]}
    assert (await admin_client.put(f"/api/v1/buyer/tasks/{task_id}", json=body)).status_code == 200
    mock_market(search)
    stats = await run_task(task_id)
    assert stats.new == 0 and stats.recommended == 1
    set_llm(None)


@respx.mock
async def test_buyer_task_backs_off_on_risk_instead_of_pausing(admin_client):
    from datetime import UTC, datetime

    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    search = respx.post(url__regex=r".*idlemtopsearch.*").mock(
        return_value=httpx.Response(200, json={"ret": ["RGV587_ERROR::SM::哎哟喂,被挤爆啦"], "data": {}})
    )
    task_id = (await admin_client.post("/api/v1/buyer/tasks", json={**TASK, "decision_mode": "rule"})).json()["id"]
    await run_task(task_id)
    task = (await admin_client.get(f"/api/v1/buyer/tasks/{task_id}")).json()
    assert task["last_status"] == "risk" and task["paused_reason"] is None and task["enabled"]
    retry_at = datetime.fromisoformat(task["retry_at"])
    retry_at = retry_at if retry_at.tzinfo else retry_at.replace(tzinfo=UTC)
    assert retry_at > datetime.now(UTC)
    async with session_factory()() as s:
        assert (await s.execute(select(TaskResult))).first() is None

    # 退避期内的定时触发直接跳过，不再去碰闲鱼
    calls = search.call_count
    stats = await run_task(task_id)
    assert "等待风控退避重试" in stats.notes and search.call_count == calls

    # 手动「立即搜索」取消等待；成功后清除重试
    search.mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": load("search_response.json")["data"]})
    )
    get_runtime().gateway.guard.load(account_key(None), "active")
    assert (await admin_client.post(f"/api/v1/buyer/tasks/{task_id}/run")).status_code == 202
    from app.domains.buyer.router import _background

    await asyncio.gather(*list(_background))
    assert search.call_count > calls
    task = (await admin_client.get(f"/api/v1/buyer/tasks/{task_id}")).json()
    assert task["last_status"] == "ok" and task["retry_at"] is None


@respx.mock
async def test_repeated_risk_alerts_once_with_a_hint(admin_client):
    from app.domains.buyer.models import MonitorTask
    from app.domains.buyer.pipeline import RISK_ALERT_AFTER

    hook = respx.post("https://hook.example.com/t").mock(return_value=httpx.Response(200))
    await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "h", "type": "webhook", "config": {"url": "https://hook.example.com/t"}},
    )
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    respx.post(url__regex=r".*idlemtopsearch.*").mock(
        return_value=httpx.Response(200, json={"ret": ["RGV587_ERROR::SM::哎哟喂,被挤爆啦"], "data": {}})
    )
    task_id = (await admin_client.post("/api/v1/buyer/tasks", json={**TASK, "decision_mode": "rule"})).json()["id"]
    for _ in range(RISK_ALERT_AFTER + 1):
        get_runtime().gateway.guard.load(account_key(None), "active")
        async with session_factory()() as s:
            (await s.get(MonitorTask, task_id)).retry_at = None  # 跳过退避等待
            await s.commit()
        await run_task(task_id)
    alerts = [c for c in hook.calls if "被闲鱼限制" in c.request.content.decode()]
    assert len(alerts) == 1 and "搜索账号" in alerts[0].request.content.decode()


def test_risk_retry_delay_backs_off_and_respects_cooldown():
    from app.domains.buyer.pipeline import RISK_RETRY_MAX_SECONDS, risk_retry_delay

    first, third = risk_retry_delay(1, 0), risk_retry_delay(3, 0)
    assert 120 < first <= 210 and 480 < third <= 570
    assert risk_retry_delay(20, 0) <= RISK_RETRY_MAX_SECONDS + 90
    assert risk_retry_delay(1, 1800) >= 1800  # 冷却期更长时等到冷却结束


async def test_task_validation(admin_client):
    r = await admin_client.post("/api/v1/buyer/tasks", json={**TASK, "cron": "* * * * *"})
    assert r.status_code == 422
    r = await admin_client.post("/api/v1/buyer/tasks/generate", json={"description": "想要一台 M1 Air"})
    assert r.status_code == 503  # 未配置大模型


@respx.mock
async def test_one_time_search_runs_without_enabling_monitoring(admin_client):
    body = {k: v for k, v in TASK.items() if k != "enabled"}
    body["decision_mode"] = "rule"
    response = await admin_client.post("/api/v1/buyer/tasks", json=body)
    assert response.status_code == 201
    task = response.json()
    assert task["enabled"] is False

    # 周期触发不执行手动记录；明确的手动触发仍然真实采集并保存结果。
    assert (await run_task(task["id"])).fetched == 0
    assert (await admin_client.get(f"/api/v1/buyer/tasks/{task['id']}")).json()["last_run_at"] is None
    mock_market(load("search_response.json")["data"])
    response = await admin_client.post(f"/api/v1/buyer/tasks/{task['id']}/run")
    assert response.status_code == 202
    from app.domains.buyer.router import _background

    await asyncio.gather(*list(_background))
    task = (await admin_client.get(f"/api/v1/buyer/tasks/{task['id']}")).json()
    assert task["enabled"] is False and task["last_status"] == "ok"
    assert task["last_stats"]["fetched"] == 2


async def test_monitoring_only_registers_jobs_after_opt_in(admin_client, monkeypatch):
    from app.domains.buyer import scheduling

    jobs = {}
    monkeypatch.setattr(scheduling, "_enabled", True)
    monkeypatch.setattr(scheduling.scheduler, "add_cron_job", lambda key, *args, **kwargs: jobs.update({key: args}))
    monkeypatch.setattr(scheduling.scheduler, "remove_job", lambda key: jobs.pop(key, None))
    body = {k: v for k, v in TASK.items() if k != "enabled"}
    task = (await admin_client.post("/api/v1/buyer/tasks", json=body)).json()
    assert jobs == {}
    response = await admin_client.put(f"/api/v1/buyer/tasks/{task['id']}", json={**body, "enabled": True})
    assert response.status_code == 200 and scheduling.job_id(task["id"]) in jobs
    await admin_client.put(f"/api/v1/buyer/tasks/{task['id']}", json={**body, "enabled": False})
    assert jobs == {}


@respx.mock
async def test_live_search_and_item_detail(admin_client):
    search = load("search_response.json")["data"]
    mock_market(search)
    res = await admin_client.get("/api/v1/buyer/search?keyword=macbook&page=1&sort=newest")
    assert res.status_code == 200
    data = res.json()
    assert len(data["items"]) == 2
    assert data["items"][0]["title"]
    assert data["items"][0]["item_id"] == "900000000001"
    ok = await admin_client.get("/api/v1/buyer/search?keyword=m&sort=reduce&quick_filters=filterAppraise,filterNew")
    assert ok.status_code == 200
    bad = await admin_client.get("/api/v1/buyer/search?keyword=m&quick_filters=filterAppraise,hack")
    assert bad.status_code == 422 and "hack" in bad.text

    detail_res = await admin_client.get("/api/v1/buyer/items/900000000001/detail")
    assert detail_res.status_code == 200
    detail = detail_res.json()
    assert detail["item"]["item_id"] == "900000000001"
    assert detail["seller"]["nick"]


@respx.mock
async def test_search_rate_limit_reports_real_cooldown(admin_client):
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    respx.post(url__regex=r".*idlemtopsearch.*").mock(
        return_value=httpx.Response(200, json={"ret": ["RGV587_ERROR::SM::哎哟喂,被挤爆啦"], "data": {}})
    )
    assert (await admin_client.get("/api/v1/buyer/search/status")).json()["cooldown_seconds"] == 0

    r = await admin_client.get("/api/v1/buyer/search?keyword=iphone")
    assert r.status_code == 429
    left = int(r.headers["retry-after"])
    assert 100 <= left <= 120  # 首次限流冷却 2 分钟
    assert "匿名通道" in r.json()["detail"] and "2 分钟" in r.json()["detail"] and "RGV587" not in r.json()["detail"]

    # 冷却期内再搜：不再请求闲鱼，直接告知剩余时间
    r = await admin_client.get("/api/v1/buyer/search?keyword=iphone")
    assert r.status_code == 423 and int(r.headers["retry-after"]) > 0
    status = (await admin_client.get("/api/v1/buyer/search/status")).json()
    assert status["state"] == "cooldown" and status["cooldown_seconds"] > 0 and status["strikes"] == 1


@respx.mock
async def test_manual_search_falls_back_to_account_when_anonymous_is_limited(admin_client):
    from tests.test_accounts import COOKIES, mock_probe

    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    search = load("search_response.json")["data"]
    calls = {"anon": 0, "acc": 0}

    def handler(request):
        if "unb=2200888" in request.headers.get("cookie", ""):
            calls["acc"] += 1
            return httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": search})
        calls["anon"] += 1
        return httpx.Response(200, json={"ret": ["RGV587_ERROR::SM::哎哟喂,被挤爆啦"], "data": {}})

    respx.post(url__regex=r".*idlemtopsearch.*").mock(side_effect=handler)

    r = await admin_client.get("/api/v1/buyer/search?keyword=iphone")
    assert r.status_code == 200, r.text
    ch = r.json()["channel"]
    assert ch == {"type": "account", "account_id": acc["id"], "name": ch["name"], "fallback": True} and ch["name"]
    assert calls == {"anon": 1, "acc": 1} and len(r.json()["items"]) == 2
    assert (await admin_client.get("/api/v1/buyer/search/status")).json()["fallback_account"]["id"] == acc["id"]

    # 匿名通道仍在暂停：直接用账号，不再试探匿名通道（以免延长闲鱼的限制）
    r = await admin_client.get("/api/v1/buyer/search?keyword=iphone")
    assert r.status_code == 200 and calls == {"anon": 1, "acc": 2}

    # 仅匿名：不借用账号
    r = await admin_client.get("/api/v1/buyer/search?keyword=iphone&fallback=false")
    assert r.status_code == 423 and calls["acc"] == 2

    # 商品详情 / 商品分析 / 商家分析同样静默改用账号
    detail_calls = {"anon": 0, "acc": 0}

    def detail_handler(request):
        key = "acc" if "unb=2200888" in request.headers.get("cookie", "") else "anon"
        detail_calls[key] += 1
        return httpx.Response(200, json=load("detail_response.json"))

    respx.post(url__regex=r".*mtop\.taobao\.idle\.pc\.detail.*").mock(side_effect=detail_handler)
    r = await admin_client.get("/api/v1/buyer/items/900000000001/detail")
    assert r.status_code == 200, r.text
    assert detail_calls == {"anon": 0, "acc": 1}

    # 价格监控：加入与「立即检查」
    w = await admin_client.post("/api/v1/buyer/watches", json={"item": "900000000001", "target_price": 1})
    assert w.status_code == 201, w.text
    assert (await admin_client.post(f"/api/v1/buyer/watches/{w.json()['id']}/check")).status_code == 200
    assert detail_calls == {"anon": 0, "acc": 3}

    # 卖家查同款行情
    r = await admin_client.get("/api/v1/goods/market?keyword=macbook")
    assert r.status_code == 200, r.text
    assert calls == {"anon": 1, "acc": 3}

    # 智能搜索「立即搜索」：本次用账号，任务设置仍是匿名
    from app.domains.buyer.router import _background

    task = (await admin_client.post("/api/v1/buyer/tasks", json={**TASK, "decision_mode": "rule"})).json()
    assert (await admin_client.post(f"/api/v1/buyer/tasks/{task['id']}/run")).status_code == 202
    await asyncio.gather(*list(_background))
    assert calls["anon"] == 1 and calls["acc"] > 3
    task = (await admin_client.get(f"/api/v1/buyer/tasks/{task['id']}")).json()
    assert task["last_status"] == "ok" and task["account_id"] is None


def test_sync_task_schedules_and_cancels_backoff_retry(monkeypatch):
    from datetime import UTC, datetime, timedelta

    from app.domains.buyer import scheduling
    from app.domains.buyer.models import MonitorTask
    from app.workers import scheduler

    monkeypatch.setattr(scheduling, "_enabled", True)
    task = MonitorTask(id=987, enabled=True, cron="*/30 8-23 * * *", retry_at=datetime.now(UTC) + timedelta(minutes=5))
    try:
        scheduling.sync_task(task)
        job = scheduler.get_scheduler().get_job(scheduling.retry_job_id(987))
        assert job is not None and list(job.args) == [987]
        task.retry_at = None
        scheduling.sync_task(task)
        assert scheduler.get_scheduler().get_job(scheduling.retry_job_id(987)) is None
    finally:
        scheduling.remove_task(987)
