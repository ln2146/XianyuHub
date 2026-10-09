import copy

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_factory
from app.domains.buyer.models import PriceSnapshot, PriceWatch
from app.domains.buyer.watch import WatchInputError, check_due_watches, parse_item_id
from tests.test_goofish_protocol import load

ITEM = "900000000001"


def mock_detail(price: str = "3200", status: str = "在售", ret: list[str] | None = None):
    data = copy.deepcopy(load("detail_response.json"))
    data["data"]["itemDO"]["soldPrice"] = price
    data["data"]["itemDO"]["itemStatusStr"] = status
    if ret:
        data = {"ret": ret, "data": {}}
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    respx.post(url__regex=r".*mtop\.taobao\.idle\.pc\.detail.*").mock(return_value=httpx.Response(200, json=data))


async def _hook(admin_client):
    hook = respx.post("https://hook.example.com/n").mock(return_value=httpx.Response(200))
    await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "h", "type": "webhook", "config": {"url": "https://hook.example.com/n"}},
    )
    return hook


async def _make_due(watch_id: int) -> None:
    async with session_factory()() as s:
        w = await s.get(PriceWatch, watch_id)
        w.last_checked_at = None
        await s.commit()


def test_parse_item_id():
    assert parse_item_id(" 900000000001 ") == ITEM
    assert parse_item_id("https://www.goofish.com/item?spm=a.b&id=900000000001&categoryId=1") == ITEM
    assert parse_item_id("https://2.taobao.com/item.htm?id=900000000001") == ITEM
    for bad in ("https://m.tb.cn/h.abc", "hello"):
        try:
            parse_item_id(bad)
        except WatchInputError:
            pass
        else:  # pragma: no cover
            raise AssertionError(bad)


@respx.mock
async def test_price_watch_lifecycle(admin_client):
    hook = await _hook(admin_client)
    mock_detail("3200")

    # 必须至少一个提醒条件
    r = await admin_client.post("/api/v1/buyer/watches", json={"item": ITEM})
    assert r.status_code == 422
    # 目标价已满足 → 拒绝
    r = await admin_client.post("/api/v1/buyer/watches", json={"item": ITEM, "target_price": 3500})
    assert r.status_code == 422 and "已满足" in r.text

    r = await admin_client.post(
        "/api/v1/buyer/watches",
        json={"item": f"https://www.goofish.com/item?id={ITEM}", "target_price": 3000, "interval_minutes": 30},
    )
    assert r.status_code == 201, r.text
    w = r.json()
    assert w["base_price"] == 3200 and w["last_price"] == 3200 and w["status"] == "watching"
    assert w["title"].startswith("自用 MacBook")
    # 重复添加
    r = await admin_client.post("/api/v1/buyer/watches", json={"item": ITEM, "target_price": 3000})
    assert r.status_code == 409

    # 刚检查过，未到期 → 本轮不检查
    assert await check_due_watches() == 0

    # 小幅降价，未达目标价：记录价格，不提醒
    mock_detail("3100")
    await _make_due(w["id"])
    assert await check_due_watches() == 1
    assert not hook.called
    w = (await admin_client.get("/api/v1/buyer/watches")).json()[0]
    assert w["last_price"] == 3100 and w["lowest_price"] == 3100 and w["status"] == "watching"

    # 降到目标价以下：提醒一次并自动暂停
    mock_detail("2900")
    await _make_due(w["id"])
    assert await check_due_watches() == 1
    assert hook.call_count == 1 and "到价提醒" in hook.calls[-1].request.content.decode()
    w = (await admin_client.get("/api/v1/buyer/watches")).json()[0]
    assert w["status"] == "triggered" and w["enabled"] is False and w["triggered_at"]
    # 已暂停，不再检查
    await _make_due(w["id"])
    assert await check_due_watches() == 0

    # 价格走势复用市场商品库快照
    async with session_factory()() as s:
        prices = [
            p.price for p in (await s.execute(select(PriceSnapshot).where(PriceSnapshot.item_id == ITEM))).scalars()
        ]
    assert prices == [3200, 3100, 2900]

    # 重新开启：条件仍满足 → 拒绝；调低目标价后可以开启，基准价更新为当前价
    body = {"target_price": 3000, "interval_minutes": 30, "enabled": True}
    r = await admin_client.put(f"/api/v1/buyer/watches/{w['id']}", json=body)
    assert r.status_code == 422
    r = await admin_client.put(f"/api/v1/buyer/watches/{w['id']}", json={**body, "target_price": 2500})
    assert r.status_code == 200, r.text
    assert r.json()["status"] == "watching" and r.json()["base_price"] == 2900

    # 商品售出 → 自动停止并通知
    mock_detail("2900", status="已售出")
    r = await admin_client.post(f"/api/v1/buyer/watches/{w['id']}/check")
    assert r.status_code == 200
    assert r.json()["status"] == "ended" and r.json()["enabled"] is False
    assert "已停止监控" in hook.calls[-1].request.content.decode()
    r = await admin_client.put(f"/api/v1/buyer/watches/{w['id']}", json={**body, "target_price": 2000})
    assert r.status_code == 409

    assert (await admin_client.delete(f"/api/v1/buyer/watches/{w['id']}")).status_code == 204
    assert (await admin_client.get("/api/v1/buyer/watches")).json() == []


@respx.mock
async def test_price_watch_drop_percent_and_deleted_item(admin_client):
    hook = await _hook(admin_client)
    mock_detail("1000")
    r = await admin_client.post("/api/v1/buyer/watches", json={"item": ITEM, "drop_percent": 20})
    assert r.status_code == 201, r.text
    wid = r.json()["id"]

    mock_detail("850")  # 降 15%，未达 20%
    await _make_due(wid)
    await check_due_watches()
    assert not hook.called

    mock_detail("790")  # 降 21%
    await _make_due(wid)
    await check_due_watches()
    assert "降价 21%" in hook.calls[-1].request.content.decode()

    # 商品被删除：业务错误视为结束
    r = await admin_client.put(f"/api/v1/buyer/watches/{wid}", json={"drop_percent": 30, "enabled": True})
    assert r.status_code == 200 and r.json()["base_price"] == 790
    mock_detail(ret=["FAIL_BIZ_ITEM_NOT_EXIST::商品不存在"])
    await _make_due(wid)
    await check_due_watches()
    w = (await admin_client.get("/api/v1/buyer/watches")).json()[0]
    assert w["status"] == "ended" and "不可访问" in w["ended_reason"]
