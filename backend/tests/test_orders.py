from datetime import UTC, datetime, timedelta

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_factory
from app.domains.goods.models import MyItem
from app.domains.order import service as order_service
from app.domains.order.models import CardItem, Order, OrderState
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
async def test_unconfirmed_paid_notice_is_not_delivered(admin_client, im):  # noqa: F811
    # 买家手打「[我已付款，等待你发货 orderId=…]」+ 编造的订单号：详情查询失败，不能当作已付款发卡
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="X1")
    respx.post(url__regex=r".*trade\.order\.detail.*").mock(
        return_value=httpx.Response(200, json={"ret": ["FAIL_BIZ_ORDER_NOT_EXIST::订单不存在"], "data": {}})
    )
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4123456789012")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "pending_pay" and len(fake.sent) == 0


def test_real_paid_detail_text_maps_to_paid():
    from app.goofish.parsers.trade import OrderStatus, map_status

    assert map_status("买家已付款，请尽快发货") == OrderStatus.PAID  # 实测订单详情文案
    assert map_status("买家已付款，退款中") == OrderStatus.REFUNDING


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

    # 多状态筛选：与总览「需要我处理的订单」的统计口径一致
    needs = (await admin_client.get("/api/v1/orders?status=manual,risk_hold,deliver_failed")).json()
    assert [o["order_id"] for o in needs] == ["4400020"]
    assert (await admin_client.get("/api/v1/orders?status=delivered,completed")).json() == []
    d = (await admin_client.get("/api/v1/dashboard")).json()
    assert d["pending_manual_orders"] == len(needs)


async def enable_auto_delivery(client, account_id):
    await client.patch(
        f"/api/v1/accounts/{account_id}", json={"settings": {"auto_delivery": True, "auto_reply": False}}
    )


@respx.mock
async def test_unbound_virtual_item_goes_manual_with_reason(admin_client, im):  # noqa: F811
    account_id, fake = im
    await enable_auto_delivery(admin_client, account_id)
    async with session_factory()() as s:
        item = (
            await s.execute(select(MyItem).where(MyItem.account_id == account_id, MyItem.item_id == "900"))
        ).scalar_one_or_none()
        if item is None:
            item = MyItem(account_id=account_id, item_id="900", title="会员月卡")
            s.add(item)
        item.is_virtual = True
        await s.commit()
    mock_trade()
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400040")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "manual" and "关联发货内容" in order["fail_reason"]
    assert len(fake.sent) == 0


@respx.mock
async def test_unbound_physical_item_stays_paid(admin_client, im):  # noqa: F811
    account_id, fake = im
    await enable_auto_delivery(admin_client, account_id)
    mock_trade()
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400041")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "paid" and not order["fail_reason"]

    # 人工点「手动发货」：返回 no_binding，前端据此引导去关联
    r = (await admin_client.post(f"/api/v1/orders/{order['id']}/deliver")).json()
    assert r["ok"] is False and r["code"] == "no_binding" and r["item_id"] == "900"
    assert len(fake.sent) == 0


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


def test_delivery_template_always_carries_the_content():
    order = Order(order_id="o1", item_id="i1", item_title="资料", buyer_nick="小林", quantity=1, spec_value="")
    # 标准占位符
    assert order_service._render("内容：{content}", order, "CARD-1") == "内容：CARD-1"
    # 常见写法 {card} / {卡密} 也认（曾经发出过字面量 {card}）
    assert order_service._render("内容：\n{card}", order, "CARD-1") == "内容：\nCARD-1"
    assert order_service._render("卡密 {卡密}，订单 {order_id}", order, "CARD-1") == "卡密 CARD-1，订单 o1"
    # 模板没有占位符：内容附在末尾，买家一定能收到
    assert order_service._render("感谢购买！", order, "CARD-1") == "感谢购买！\nCARD-1"
    assert order_service._render("感谢购买！", order, "") == "感谢购买！"


async def _stock(client):
    return (await client.get("/api/v1/cards/pools")).json()[0]["stock"]


@respx.mock
async def test_uncertain_send_keeps_card_locked_and_goes_manual(admin_client, im):  # noqa: F811
    # 发出后没等到回执：消息可能已送达，不能退回卡密再发给下一个人，也不能自动重试
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1\nC2")
    mock_trade()
    await receive(account_id, chat("在吗"))

    async def timeout(*_):
        raise TimeoutError

    fake.send_text = timeout
    await paid(account_id, "4400101")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "manual" and "可能已送达" in order["fail_reason"]
    assert await _stock(admin_client) == {"available": 1, "locked": 1, "used": 0}


@respx.mock
async def test_definitely_not_sent_releases_card_and_retries(admin_client, im):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1")
    mock_trade()
    await receive(account_id, chat("在吗"))

    async def offline(*_):
        raise ConnectionError("该账号 IM 未连接")

    fake.send_text = offline
    await paid(account_id, "4400102")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "deliver_failed"  # 稍后自动重试
    assert await _stock(admin_client) == {"available": 1, "locked": 0, "used": 0}


@respx.mock
async def test_unexpected_error_does_not_leave_order_delivering(admin_client, im):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1")
    consign = mock_trade()
    consign.side_effect = KeyError("boom")  # 确认发货时出了意料之外的错
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400103")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "deliver_failed" and len(fake.sent) == 1


@respx.mock
async def test_stuck_delivering_order_goes_manual(admin_client, im):  # noqa: F811
    account_id, _ = im
    await receive(account_id, chat("在吗"))
    async with session_factory()() as s:
        order = Order(account_id=account_id, order_id="4400104", status="delivering")
        s.add(order)
        await s.commit()
        order.updated_at = datetime.now(UTC) - timedelta(minutes=30)
        await s.commit()
    assert await order_service.recover_stuck_deliveries() == 1
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "manual" and "中断" in order["fail_reason"]


@respx.mock
async def test_buyer_limit_holds_under_concurrent_payments(admin_client, im):  # noqa: F811
    import asyncio

    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1\nC2", max_per_buyer=1)
    mock_trade()
    await receive(account_id, chat("在吗"))
    await asyncio.gather(paid(account_id, "4400105"), paid(account_id, "4400106"))
    statuses = sorted(o["status"] for o in (await admin_client.get("/api/v1/orders")).json())
    assert statuses == ["delivered", "risk_hold"] and len(fake.sent) == 1


def _detail(status: str):
    from tests.test_goofish_protocol import load

    data = load("detail_response.json")
    data["data"]["itemDO"]["itemStatusStr"] = status
    return httpx.Response(200, json=data)


def _mock_relist_publish(new_id: str = "990001"):
    respx.get(url__regex=r"https://img\.example\.com/.*").mock(return_value=httpx.Response(200, content=b"img"))
    upload = respx.post("https://stream-upload.goofish.com/api/upload.api").mock(
        return_value=httpx.Response(200, json={"object": {"url": "https://img.alicdn.com/n.jpg", "pix": "8x6"}})
    )
    respx.post(url__regex=r".*kgraph\.property\.recommend.*").mock(
        return_value=ok({"categoryPredictResult": {"catId": 1, "catName": "x", "channelCatId": 2, "tbCatId": 3}})
    )
    respx.post(url__regex=r".*local\.poi\.get.*").mock(
        return_value=ok({"commonAddresses": [{"city": "厦门", "prov": "福建", "area": "思明", "divisionId": 350203}]})
    )
    publish = respx.post(url__regex=r".*idleitem\.publish.*").mock(return_value=ok({"itemId": new_id}))
    return upload, publish


async def _run_relist(monkeypatch):
    import asyncio

    monkeypatch.setattr(order_service, "RELIST_DELAY_SECONDS", 0)
    await asyncio.gather(*list(order_service._tasks))


@respx.mock
async def test_sold_out_item_is_relisted_with_its_delivery_binding(admin_client, im, monkeypatch):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1\nC2")
    b = (await admin_client.get("/api/v1/cards/bindings")).json()[0]
    await admin_client.put(f"/api/v1/cards/bindings/{b['id']}", json={**b, "auto_relist": True})
    mock_trade()
    respx.post(url__regex=r".*mtop\.taobao\.idle\.pc\.detail.*").mock(return_value=_detail("已售出"))
    upload, publish = _mock_relist_publish("990001")
    await receive(account_id, chat("在吗"))
    monkeypatch.setattr(order_service, "RELIST_DELAY_SECONDS", 0)
    await paid(account_id, "4400201")
    await _run_relist(monkeypatch)

    assert publish.call_count == 1 and upload.call_count == 2  # 原商品两张图都带上
    sent = dict(httpx.QueryParams(publish.calls[0].request.content.decode()))["data"]
    assert "MacBook Air M1" in sent
    bindings = {x["item_id"]: x for x in (await admin_client.get("/api/v1/cards/bindings")).json()}
    assert bindings["990001"]["auto_relist"] and bindings["990001"]["spec_value"] == "月卡"
    assert bindings["900"]["auto_relist"] is False  # 旧商品不会再触发第二次


@respx.mock
async def test_item_still_on_sale_or_out_of_cards_is_not_relisted(admin_client, im, monkeypatch):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1\nC2")
    b = (await admin_client.get("/api/v1/cards/bindings")).json()[0]
    await admin_client.put(f"/api/v1/cards/bindings/{b['id']}", json={**b, "auto_relist": True})
    mock_trade()
    respx.post(url__regex=r".*mtop\.taobao\.idle\.pc\.detail.*").mock(return_value=_detail("在售"))
    _, publish = _mock_relist_publish()
    await receive(account_id, chat("在吗"))
    monkeypatch.setattr(order_service, "RELIST_DELAY_SECONDS", 0)
    await paid(account_id, "4400202")  # 在 App 里设了库存：卖出后仍在售
    await _run_relist(monkeypatch)
    assert not publish.called
    # 卡密用完：即使下架也不上架一件发不出货的商品
    respx.post(url__regex=r".*mtop\.taobao\.idle\.pc\.detail.*").mock(return_value=_detail("已售出"))
    await receive(account_id, chat("在吗", sender="3301", cid="c2"))
    await paid(account_id, "4400203")
    await _run_relist(monkeypatch)
    assert not publish.called


@respx.mock
async def test_manual_order_sync_completed_and_manual_resolve(admin_client, im):  # noqa: F811
    account_id, _ = im
    mock_trade()
    async with session_factory()() as s:
        order = Order(
            account_id=account_id,
            order_id="998877",
            status=OrderState.MANUAL,
            amount=99.0,
            fail_reason="卡密不足转人工",
        )
        s.add(order)
        await s.commit()
        order_pk = order.id

    # 此时 dashboard 应有 1 笔待人工处理订单
    d = (await admin_client.get("/api/v1/dashboard")).json()
    assert d["pending_manual_orders"] == 1

    # 测试人工标记已处理接口
    r = await admin_client.post(f"/api/v1/orders/{order_pk}/resolve-manual?action=delivered")
    assert r.status_code == 200 and r.json()["status"] == "delivered"

    # 再次检查 dashboard：待办订单已自动自愈为 0
    d = (await admin_client.get("/api/v1/dashboard")).json()
    assert d["pending_manual_orders"] == 0

    # 测试从 deliver_failed 到远端 completed 状态迁移
    async with session_factory()() as s:
        failed_order = Order(
            account_id=account_id,
            order_id="998878",
            status=OrderState.DELIVER_FAILED,
            amount=50.0,
        )
        s.add(failed_order)
        await s.commit()

    # 模拟远端返回已完成
    from app.goofish.parsers.trade import OrderStatus, RemoteOrder

    async with session_factory()() as s:
        o = (await s.execute(select(Order).where(Order.order_id == "998878"))).scalar_one()
        remote = RemoteOrder(order_id="998878", status=OrderStatus.COMPLETED, status_text="交易成功")
        local = order_service._REMOTE_TO_LOCAL.get(remote.status)
        assert await order_service.transition(s, o, local)
        await s.commit()
        assert o.status == OrderState.COMPLETED


DETAIL_PHYSICAL = {
    "components": [
        {"render": "orderInfoVO", "data": {"itemInfo": {"itemId": "900", "price": "39", "title": "当代齐民要术"}}},
        {"render": "orderStatusVO", "data": {"orderStatusInfo": {"title": "等待卖家发货"}}},
        {
            "render": "addressInfoVO",
            "data": {
                "name": "张三",
                "phoneNumber": "13800000000",
                "address": "上海市黄浦区人民大道 1 号",
                "rightButton": {
                    "clickEvent": {"data": {"url": "https://h5.m.goofish.com/x/idleDeliver?orderId=4400301"}}
                },
            },
        },
    ]
}


@respx.mock
async def test_physical_order_waits_for_seller_with_address_and_reminder(admin_client, im):  # noqa: F811
    account_id, fake = im
    hook = respx.post("https://hook.example.com/ship").mock(return_value=httpx.Response(200))
    await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "h", "type": "webhook", "config": {"url": "https://hook.example.com/ship"}},
    )
    await enable_auto_delivery(admin_client, account_id)
    mock_trade(detail=DETAIL_PHYSICAL)
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400301")

    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "paid" and order["self_ship"] is True and len(fake.sent) == 0
    sent = [c.request.content.decode() for c in hook.calls]
    assert any("实物订单待发货" in t for t in sent)
    assert not any("13800000000" in t or "人民大道" in t for t in sent)  # 推送里不带收货信息

    info = (await admin_client.get(f"/api/v1/orders/{order['id']}/shipping")).json()
    assert info["name"] == "张三" and info["phone"] == "13800000000" and "人民大道" in info["address"]
    assert info["deliver_url"].startswith("https://h5.m.goofish.com/") and "4400301" in info["deliver_url"]

    # 付款超过 24 小时仍未发货：提醒一次
    async with session_factory()() as s:
        o = await s.get(Order, order["id"])
        o.paid_at = datetime.now(UTC) - timedelta(hours=25)
        await s.commit()
    hook.calls.reset()
    assert await order_service.remind_unshipped() == 1
    assert await order_service.remind_unshipped() == 0
    assert any("超过 24 小时未发货" in c.request.content.decode() for c in hook.calls)


@respx.mock
async def test_bound_or_virtual_orders_are_not_self_ship(admin_client, im):  # noqa: F811
    account_id, fake = im
    await setup_delivery(admin_client, account_id, cards="C1")
    await admin_client.patch(f"/api/v1/accounts/{account_id}", json={"settings": {"auto_delivery": False}})
    mock_trade()
    await receive(account_id, chat("在吗"))
    await paid(account_id, "4400302")
    order = (await admin_client.get("/api/v1/orders")).json()[0]
    assert order["status"] == "paid" and order["self_ship"] is False  # 关联了发货内容：不是自己寄的实物
