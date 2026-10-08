import httpx
import respx
from sqlalchemy import select

from app.core.db import session_factory
from app.domains.buyer.models import MarketItemRecord, PriceSnapshot, TaskResult
from app.domains.buyer.pipeline import run_task
from app.intelligence.llm import LLMGateway, LLMResult, set_llm
from tests.test_goofish_protocol import load

TASK = {
    "name": "M1 Air",
    "keywords": ["macbook air m1"],
    "max_price": 4000,
    "rules": {"exclude": ["配件"]},
    "criteria": "必须：M1 芯片；电池 ≥ 85%",
    "cron": "*/30 8-23 * * *",
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
async def test_buyer_task_pauses_on_risk(admin_client):
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    respx.post(url__regex=r".*idlemtopsearch.*").mock(
        return_value=httpx.Response(200, json={"ret": ["RGV587_ERROR::SM::哎哟喂,被挤爆啦"], "data": {}})
    )
    task_id = (await admin_client.post("/api/v1/buyer/tasks", json={**TASK, "decision_mode": "rule"})).json()["id"]
    await run_task(task_id)
    task = (await admin_client.get(f"/api/v1/buyer/tasks/{task_id}")).json()
    assert task["last_status"] == "risk" and task["paused_reason"]
    async with session_factory()() as s:
        assert (await s.execute(select(TaskResult))).first() is None


async def test_task_validation(admin_client):
    r = await admin_client.post("/api/v1/buyer/tasks", json={**TASK, "cron": "* * * * *"})
    assert r.status_code == 422
    r = await admin_client.post("/api/v1/buyer/tasks/generate", json={"description": "想要一台 M1 Air"})
    assert r.status_code == 503  # 未配置大模型
