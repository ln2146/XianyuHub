import json
import time

import httpx
import pytest
import respx

from app.goofish.dto import SearchQuery
from app.goofish.errors import RiskBlockedError, RiskControlError, SessionExpiredError
from app.goofish.gateway import GoofishGateway
from app.goofish.guard.guard import AccountState, RiskGuard
from app.goofish.guard.limiter import MemoryRateLimiter
from app.goofish.guard.policy import Action
from app.goofish.parsers.trade import OrderStatus
from app.goofish.publish import PublishDraft, ShippingMode, UploadedImage, build_publish_payload
from tests.test_goofish_protocol import load


class DictStore:
    def __init__(self):
        self.cookies = {1: {"unb": "1000", "cookie2": "c2", "_m_h5_tk": "tok_1"}}
        self.saved = []

    async def load_cookies(self, account_id):
        return dict(self.cookies[account_id])

    async def save_cookies(self, account_id, cookies):
        self.saved.append((account_id, cookies))

    async def get_proxy(self, account_id):
        return None


def ok(data):
    return httpx.Response(200, json={"ret": ["SUCCESS::调用成功"], "data": data})


def mtop_route(api: str):
    return respx.post(url__regex=rf"https://h5api\.m\.goofish\.com/h5/{api.replace('.', r'\.')}/.*")


# ------------------------------------------------------------------ limiter / guard
async def test_memory_limiter_waits_after_burst():
    lim = MemoryRateLimiter()
    assert await lim.reserve("k", rate=60, per=60, burst=2) == 0
    assert await lim.reserve("k", rate=60, per=60, burst=2) == 0
    wait = await lim.reserve("k", rate=60, per=60, burst=2)
    assert 0.5 < wait <= 1.0


async def test_guard_trips_on_risk_and_recovers():
    guard = RiskGuard()
    changes = []

    async def listener(key, rt, reason):
        changes.append((key, rt.state))

    guard.on_state_change(listener)

    async def risky():
        raise RiskControlError("滑块", punish_url="https://punish")

    with pytest.raises(RiskControlError):
        await guard.run("acc:1", Action.ORDER_QUERY, risky)
    rt = guard.runtime("acc:1")
    assert rt.state == AccountState.CIRCUIT_OPEN and rt.punish_url == "https://punish"
    assert changes[-1] == ("acc:1", AccountState.CIRCUIT_OPEN)

    async def fine():
        return 1

    with pytest.raises(RiskBlockedError):
        await guard.run("acc:1", Action.ORDER_QUERY, fine)

    await guard.resolve("acc:1")
    assert rt.state == AccountState.COOLDOWN
    rt.cooldown_until = time.time() - 1  # 冷却结束
    assert await guard.run("acc:1", Action.ORDER_QUERY, fine) == 1
    assert rt.state == AccountState.ACTIVE
    assert rt.health < 100  # strikes 仍计入健康度


async def test_guard_session_expired_blocks_login_actions_only():
    guard = RiskGuard()

    async def expired():
        raise SessionExpiredError("expired")

    with pytest.raises(SessionExpiredError):
        await guard.run("acc:2", Action.ORDER_QUERY, expired)
    assert guard.runtime("acc:2").state == AccountState.NEED_LOGIN

    async def fine():
        return "ok"

    with pytest.raises(RiskBlockedError):
        await guard.run("acc:2", Action.CONSIGN, fine)


async def test_guard_rejects_when_queue_too_long(monkeypatch):
    monkeypatch.setenv("GUARD_RATE_MULTIPLIER", "1")
    from app.core.config import get_settings

    get_settings.cache_clear()
    guard = RiskGuard()

    async def fine():
        return 1

    # 预先占满队列：EDIT_ITEM 每分钟 1 次、最多排队 120 秒
    for _ in range(3):
        await guard.limiter.reserve("acc:3:edit_item", 1, 60, 1)
    with pytest.raises(RiskBlockedError) as ei:
        await guard.run("acc:3", Action.EDIT_ITEM, fine)
    assert ei.value.state == "rate_limited" and ei.value.retry_after > 120


# ------------------------------------------------------------------ gateway
@respx.mock
async def test_gateway_anonymous_search():
    route = mtop_route("mtop.taobao.idlemtopsearch.pc.search").mock(
        return_value=ok(load("search_response.json")["data"])
    )
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(
            200, json={"ret": ["FAIL_SYS_TOKEN_EMPTY"], "data": {}}, headers={"set-cookie": "_m_h5_tk=anon_1; Path=/"}
        )
    )
    gw = GoofishGateway(DictStore(), RiskGuard())
    page = await gw.search_items(SearchQuery(keyword="macbook", max_price=4000))
    assert len(page.items) == 2
    body = json.loads(dict(httpx.QueryParams(route.calls[0].request.content.decode()))["data"])
    assert body["keyword"] == "macbook" and "priceRange:0,4000;" in body["propValueStr"]["searchFilter"]
    await gw.aclose()


@respx.mock
async def test_gateway_orders_and_consign_and_cookie_persist():
    store = DictStore()
    mtop_route("mtop.taobao.idle.trade.merchant.sold.get").mock(
        return_value=httpx.Response(
            200,
            json={
                "ret": ["SUCCESS::调用成功"],
                "data": {
                    "module": {
                        "nextPage": "false",
                        "items": [
                            {
                                "commonData": {
                                    "orderId": "4400001",
                                    "orderStatus": "待发货",
                                    "itemId": "900",
                                    "createTime": "2026-10-01 12:00:00",
                                },
                                "buyerInfoVO": {"buyerId": "3300", "userNick": "买家A"},
                                "priceVO": {"totalPrice": "19.90", "buyNum": "1"},
                                "rightVO": {"btnList": [{"tradeAction": "SKIP_PIN"}]},
                            }
                        ],
                    }
                },
            },
            headers={"set-cookie": "_m_h5_tk=tok2_2; Path=/"},
        )
    )
    mtop_route("mtop.idle.web.trade.order.detail").mock(
        return_value=ok(
            {
                "components": [
                    {
                        "render": "orderInfoVO",
                        "data": {"itemInfo": {"itemId": "900", "price": "19.9", "skuInfo": "套餐:月卡"}},
                    },
                    {"render": "orderStatusVO", "data": {"orderStatusInfo": {"title": "等待卖家发货"}}},
                    {"render": "buyerInfo", "data": {"buyerId": "3300"}},
                ]
            }
        )
    )
    consign = mtop_route("mtop.taobao.idle.logistic.consign.dummy").mock(return_value=ok({}))
    gw = GoofishGateway(store, RiskGuard())

    orders, more = await gw.list_sold_orders(1)
    assert not more and orders[0].status == OrderStatus.PAID and orders[0].is_bargain
    assert store.saved and store.saved[-1][1]["_m_h5_tk"] == "tok2_2"

    detail = await gw.get_order_detail(1, "4400001")
    assert detail.spec_name == "套餐" and detail.spec_value == "月卡" and detail.status == OrderStatus.PAID
    assert detail.buyer_id == "3300"

    await gw.consign_virtual(1, "4400001")
    sent = json.loads(dict(httpx.QueryParams(consign.calls[0].request.content.decode()))["data"])
    assert sent["orderId"] == "4400001" and sent["newUnconsign"] is True
    await gw.aclose()


def test_build_publish_payload():
    draft = PublishDraft(
        title="九成新 AirPods Pro",
        desc="自用，功能正常",
        images=[UploadedImage(url="https://img/1.jpg", width=800, height=800)],
        price=599,
        orig_price=1899,
        shipping=ShippingMode.FIXED,
        post_fee=8,
    )
    category = {
        "categoryPredictResult": {"catId": 1, "catName": "耳机", "channelCatId": 2, "tbCatId": 3},
        "cardList": [
            {
                "cardData": {
                    "propertyId": "p1",
                    "propertyName": "品牌",
                    "valuesList": [{"catName": "Apple", "channelCatId": "c1", "tbCatId": "t1", "isClicked": True}],
                }
            }
        ],
    }
    address = {
        "area": "浦东",
        "city": "上海",
        "divisionId": 1,
        "longitude": 1,
        "latitude": 2,
        "poiId": "x",
        "poi": "p",
        "prov": "上海",
    }
    p = build_publish_payload(draft, category, address)
    assert p["itemPriceDTO"] == {"priceInCent": "59900", "origPriceInCent": "189900"}
    assert p["itemPostFeeDTO"]["postPriceInCent"] == "800"
    assert p["itemCatDTO"]["catName"] == "耳机" and p["itemLabelExtList"][0]["text"] == "Apple"
    assert p["itemTextDTO"]["title"] == "九成新 AirPods Pro"
