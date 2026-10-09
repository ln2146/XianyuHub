import httpx
import respx

from app.core.db import session_factory
from app.domains.message.models import ChatMessage, Conversation
from app.domains.order.buyer_risk import ShopHistory, analyze_buyer, chat_signals
from app.domains.order.models import Order, OrderState
from app.goofish.dto import SellerProfile, SellerRating
from app.intelligence.llm import LLMGateway, LLMResult, set_llm
from tests.test_accounts import COOKIES, mock_probe

BUYER = "3300"


def from_seller(rate: int, content: str) -> SellerRating:
    return SellerRating(rate=rate, content=content, role="卖家", created_at="2026-09-01")


def test_chat_signals_detect_risky_phrases_and_skip_negations():
    sigs = {
        s.key: s
        for s in chat_signals(
            [
                "能先发货吗，收到再付",
                "不满意就退哈",
                "加个微信聊吧",
                "我不会给差评的放心",  # 被否定，不算威胁
                "成色怎么样",
            ]
        )
    }
    assert set(sigs) == {"receive_first", "refund_preset", "off_platform"}
    assert sigs["receive_first"].evidence == ["能先发货吗，收到再付"]
    assert chat_signals(["差评警告，再不便宜我就投诉"])[0].key == "threat"


def test_analyze_buyer_flags_knife_on_receipt_and_rewards_regulars():
    risky = SellerProfile(
        seller_id=BUYER,
        buyer_credit="买家信用一般",
        ratings=[
            from_seller(-1, "到手刀，收货后说有划痕要退一半"),
            from_seller(0, "事多，压价"),
            from_seller(1, "还行"),
            SellerRating(rate=1, content="卖家人很好", role="买家"),  # 他作为卖家收到的，不计入
        ],
    )
    a = analyze_buyer(BUYER, risky, messages=["先发货吧，到手再付"], bargain_rounds=4)
    assert a.as_buyer == 3 and a.as_buyer_negative == 2
    assert dict(a.negative_hits)["到手刀"] == 1 and "压价" in dict(a.negative_hits)
    assert a.verdict == "decline" and a.level == "建议不卖"
    assert any("打包视频" in t for t in a.precautions)
    assert any("先发货" in r for r in a.risks) and any("4 轮" in r for r in a.risks)

    good = SellerProfile(
        seller_id="1",
        buyer_credit="买家信用极好",
        ratings=[from_seller(1, "爽快，秒付，好买家") for _ in range(12)],
    )
    b = analyze_buyer("1", good, history=ShopHistory(orders=2, completed=2))
    assert b.verdict == "sell" and b.level == "放心卖" and b.score > 85
    assert any("老顾客" in h for h in b.highlights)

    black = analyze_buyer("1", good, history=ShopHistory(blacklisted=True, blacklist_reason="仅退款"))
    assert black.score <= 20 and black.risks[0].startswith("已在你的黑名单")

    # 主页拉取失败也能基于聊天给结论
    offline = analyze_buyer(BUYER, None, messages=["加v私聊"], profile_error="风控限制")
    assert offline.chat_signals and any("未能获取买家主页" in r for r in offline.risks)


def mock_buyer_profile():
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    head = {
        "module": {
            "base": {
                "displayName": "买家A",
                "ylzTags": [{"text": "买家信用良好", "attributes": {"role": "buyer"}}],
            },
            "tabs": {"item": {"number": 2}, "rate": {"number": 2}},
        }
    }
    respx.post(url__regex=r".*user\.page\.head.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": head})
    )
    respx.post(url__regex=r".*xyh\.item\.list.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": {"cardList": [], "nextPage": False}})
    )
    rates = [
        {"rate": -1, "feedback": "到手刀，要求仅退款", "gmtCreate": "1759900000000", "rateTagList": [{"text": "卖家"}]}
    ]
    respx.post(url__regex=r".*trade\.rate\.list.*").mock(
        return_value=httpx.Response(
            200,
            json={"ret": ["SUCCESS::ok"], "data": {"cardList": [{"cardData": r} for r in rates], "nextPage": False}},
        )
    )


@respx.mock
async def test_buyer_risk_endpoints_by_conversation_and_order(admin_client):
    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    mock_buyer_profile()
    async with session_factory()() as s:
        conv = Conversation(account_id=acc["id"], cid="c1", peer_id=BUYER, peer_name="买家A", bargain_rounds=1)
        s.add(conv)
        await s.flush()
        for direction, text in [("in", "便宜点，先发货我收到再付"), ("out", "需要拍下付款哦"), ("in", "不满意就退")]:
            s.add(
                ChatMessage(
                    conversation_id=conv.id, account_id=acc["id"], direction=direction, source="buyer", text=text
                )
            )
        s.add(Order(account_id=acc["id"], order_id="o1", buyer_id=BUYER, status=OrderState.REFUNDED, amount=99))
        order = Order(account_id=acc["id"], order_id="o2", buyer_id=BUYER, status=OrderState.PAID, amount=199)
        s.add(order)
        await s.commit()
        conv_id, order_pk = conv.id, order.id

    r = await admin_client.post("/api/v1/buyer-risk/analysis", json={"conv_id": conv_id})
    assert r.status_code == 200, r.text
    a = r.json()
    assert a["buyer_id"] == BUYER and a["buyer_credit"] == "买家信用良好"
    assert {s["key"] for s in a["chat_signals"]} == {"receive_first", "refund_preset"}
    assert a["history"]["refunded"] == 1 and a["history"]["orders"] == 2
    assert dict(map(tuple, a["negative_hits"]))["到手刀"] == 1
    assert a["verdict"] == "decline"

    # 从订单进入：自动找到同一买家的会话
    r = await admin_client.post("/api/v1/buyer-risk/analysis", json={"order_pk": order_pk})
    assert r.status_code == 200 and r.json()["chat_signals"]

    # 拉黑后分数封顶
    await admin_client.post("/api/v1/orders-blacklist", json={"buyer_id": BUYER, "reason": "到手刀"})
    r = await admin_client.post("/api/v1/buyer-risk/analysis", json={"conv_id": conv_id})
    assert r.json()["history"]["blacklisted"] and r.json()["score"] <= 20

    assert (await admin_client.post("/api/v1/buyer-risk/analysis", json={})).status_code == 422
    assert (await admin_client.post("/api/v1/buyer-risk/insight", json={"conv_id": conv_id})).status_code == 503

    class FakeLLM:
        async def complete(self, **kw):
            assert "收到再付" in kw["messages"][0].content
            return LLMResult(
                text='{"verdict":"decline","summary":"有到手刀记录","chat_assessment":"要求先发货",'
                '"risk_points":["到手刀"],"precautions":["录像"],"suggested_reply":"亲，需要先在闲鱼付款哦"}',
                model="m",
            )

    set_llm(LLMGateway(provider=FakeLLM()))
    r = await admin_client.post("/api/v1/buyer-risk/insight", json={"order_pk": order_pk})
    assert r.status_code == 200, r.text
    assert r.json()["ai"]["verdict"] == "decline" and r.json()["analysis"]["buyer_id"] == BUYER
    set_llm(None)
