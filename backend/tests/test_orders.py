from datetime import UTC, datetime, timedelta

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_factory
from app.domains.order import service as order_service
from app.domains.order.models import CardItem, Order
from app.goofish.dto import SystemNotice
from tests.test_messages import BUYER, FakeIm, chat, im, receive  # noqa: F401

DETAIL_PAID = {
    "components": [
        {"render": "orderInfoVO", "data": {"itemInfo": {"itemId": "900", "price": "19.9", "skuInfo": "套餐:月卡"}}},
        {"render": "orderStatusVO", "data": {"orderStatusInfo": {"title": "等待卖家发货"}}},
    ]
}


def ok(data):
    return httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": data})


async def setup_delivery(client, account_id, *, cards: str, max_per_buyer: int = 0, mode: str = "send_then_confirm"):
    await client.patch(
        f"/api/v1/accounts/{account_id}",
        json={"settings": {"auto_delivery": True, "delivery_mode": mode, "auto_reply": False}},
    )
    pool = (await client.post("/api/v1/cards/pools", json={"name": "月卡", "kind": "pool"})).json()
    r = await client.post(f"/api/v1/cards/pools/{pool['id']}/items", json={"lines": cards})
    binding = await client.post(
        "/api/v1/cards/bindings",
        json={
            "pool_id": pool["id"],
            "item_id": "900",
            "spec_value": "月卡",
            "template": "订单 {order_id} 的兑换码：{content}",
            "max_per_buyer": max_per_buyer,
        },
    )
    assert binding.status_code == 201
    return pool["id"], r.json()


def mock_trade(detail=DETAIL_PAID, consign_ok=True):
    respx.post(url__regex=r".*trade\.order\.detail.*").mock(return_value=ok(detail))
    consign = respx.post(url__regex=r".*consign\.dummy.*").mock(
        return_value=ok({})
        if consign_ok
        else httpx.Response(200, json={"ret": ["FAIL_BIZ_ORDER_STATUS::状态异常"], "data": {}})
    )
    return consign


async def paid(account_id, order_id):
    await receive(
        account_id, chat("[我已付款，等待你发货]", is_system=True, notice=SystemNotice.PAID, order_id=order_id)
    )


@respx.mock
async def test_auto_delivery_happy_path_and_buyer_limit(admin_client, im):  # noqa: F811
    account_id, fake = im
    pool_id, imported = await setup_delivery(
        admin_client, account_id, cards="CODE-AAA-111\nCODE-BBB-222\nCODE-AAA-111", max_per_buyer=1
    )
    assert imported == {"added": 2, "duplicated": 1}
    consign = mock_trade()
    await receive(account_id, chat("你好，我拍了"))  # 先建立会话

    await paid(account_id, "4400001")
    orders = (await admin_client.get("/api/v1/orders")).json()
    assert orders[0]["status"] == "delivered" and orders[0]["spec_value"] == "月卡"
    assert fake.sent[-1][2] == "订单 4400001 的兑换码：CODE-AAA-111"
    assert consign.called
    pool = (await admin_client.get("/api/v1/cards/pools")).json()[0]
    assert pool["stock"] == {"available": 1, "locked": 0, "used": 1}
    masked = (await admin_client.get(f"/api/v1/cards/pools/{pool_id}/items")).json()
    assert all("AAA-111" not in c["masked"] for c in masked)

    # 同一买家 24 小时内第二单 → 发货前风控暂停
    await paid(account_id, "4400002")
    second = (await admin_client.get("/api/v1/orders?status=risk_hold")).json()
    assert second and "24 小时" in second[0]["fail_reason"]
    # 人工放行
    r = await admin_client.post(f"/api/v1/orders/{second[0]['id']}/deliver")
    assert r.json()["ok"] and fake.sent[-1][2].endswith("CODE-BBB-222")

    # 重复的付款事件不会重复发货
    sent_before = len(fake.sent)
    await paid(account_id, "4400001")
    assert len(fake.sent) == sent_before


@respx.mock
async def test_forged_paid_message_is_not_delivered(admin_client, im):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="X1")
    pending = {"components": [{"render": "orderStatusVO", "data": {"orderStatusInfo": {"title": "等待买家付款"}}}]}
    mock_trade(detail=pending)
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400009")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "pending_pay" and len(fake.sent) == 0


@respx.mock
async def test_consign_failure_keeps_card_and_retries(admin_client, im):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="ONLY-ONE-CARD", mode="send_then_confirm")
    mock_trade(consign_ok=False)
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400010")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "deliver_failed" and order["retry_count"] == 1
    # 内容已发给买家：卡密保持占用，不会再分配给别人
    async with session_factory()() as s:
        card = (await s.execute(select(CardItem))).scalar_one()
        assert card.status == "locked"

    mock_trade(consign_ok=True)
    async with session_factory()() as s:
        o = (await s.execute(select(Order))).scalar_one()
        o.next_retry_at = datetime.now(UTC) - timedelta(seconds=1)
        await s.commit()
    sent_before = len(fake.sent)
    await order_service.retry_failed()
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    # 重试只补做确认发货，不重新分配卡密、不重复发消息
    assert order["status"] == "delivered" and len(fake.sent) == sent_before
    async with session_factory()() as s:
        card = (await s.execute(select(CardItem))).scalar_one()
        assert card.status == "used"


@respx.mock
async def test_out_of_stock_goes_manual(admin_client, im):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="")
    mock_trade()
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400020")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "manual" and "库存不足" in order["fail_reason"]


@respx.mock
async def test_dashboard(admin_client, im):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1")
    mock_trade()
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400030")
    d = (await admin_client.get("/api/v1/dashboard")).json()
    assert d["accounts"][0]["im_connected"] and d["today"]["messages_in"] == 1
    assert d["today"]["deliveries"] == 1 and d["today"]["orders"]["delivered"] == 1
    assert d["today"]["gmv"] == 19.9 and "llm" in d["system"]
