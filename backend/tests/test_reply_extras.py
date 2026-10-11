"""自动回复的补充能力：售前 / 售后区分、黑名单、转人工规则、默认议价、AI 禁用词、图片回复与图片发货。"""

import httpx
import respx

from app.core.db import session_factory
from app.domains.goods.models import MyItem
from app.domains.message.models import Conversation
from app.domains.order.models import BuyerBlacklist, Order
from app.intelligence.guardrails import check_reply
from app.intelligence.llm import LLMGateway, LLMResult, set_llm
from tests.test_goods import PNG
from tests.test_messages import BUYER, SELLER, PriceEchoLLM, chat, im, receive  # noqa: F401
from tests.test_orders import mock_trade, paid

IMG_URL = "https://img.alicdn.com/bao/uploaded/reply.png"


class AnswerLLM:
    """意图交给规则；回复固定一句，便于断言是否由 AI 回答了。"""

    def __init__(self):
        self.prompts = []

    async def complete(self, **kw):
        if "intent" in kw["schema"]["properties"]:
            return LLMResult(text='{"intent": "other"}', model="m")
        self.prompts.append(kw["messages"][-1].content)
        return LLMResult(text='{"reply":"支持七天无理由哈","need_human":false,"reason":"ok"}', model="m")


async def _conv(account_id):
    async with session_factory()() as s:
        from sqlalchemy import select

        return (await s.execute(select(Conversation).where(Conversation.account_id == account_id))).scalar_one()


async def test_presale_after_sale_question_is_answered_not_handed_off(admin_client, im):  # noqa: F811
    account_id, fake = im
    llm = AnswerLLM()
    set_llm(LLMGateway(provider=llm))
    try:
        await receive(account_id, chat("售后怎么处理？有问题能退吗"))
        assert fake.sent[-1][2] == "支持七天无理由哈"  # 没下单：售前咨询，AI 正常回答
        assert "还没下单" in llm.prompts[-1]
        assert (await _conv(account_id)).takeover_until is None

        async with session_factory()() as s:
            s.add(Order(account_id=account_id, order_id="7700001", buyer_id=BUYER, status="delivered"))
            await s.commit()
        sent = len(fake.sent)
        await receive(account_id, chat("我要退款"))
        assert len(fake.sent) == sent  # 下过单：售后纠纷，转人工
        assert (await _conv(account_id)).takeover_until is not None
    finally:
        set_llm(None)


async def test_blacklisted_buyer_gets_no_auto_reply(admin_client, im):  # noqa: F811
    account_id, fake = im
    await admin_client.post("/api/v1/messages/rules", json={"keywords": ["发货"], "reply": "24 小时内发货"})
    async with session_factory()() as s:
        s.add(BuyerBlacklist(owner_id=1, buyer_id=BUYER, reason="恶意退款"))
        await s.commit()
    await receive(account_id, chat("什么时候发货"))
    assert fake.sent == []


async def test_handoff_rule_pauses_and_optionally_sends_a_bridge_line(admin_client, im):  # noqa: F811
    account_id, fake = im
    r = await admin_client.post(
        "/api/v1/messages/rules", json={"name": "发票", "keywords": ["发票"], "action": "handoff"}
    )
    assert r.status_code == 201 and r.json()["reply"] == ""
    await receive(account_id, chat("能开发票吗"))
    assert fake.sent == []
    assert (await _conv(account_id)).takeover_until is not None
    assert (await admin_client.get("/api/v1/messages/rules")).json()[0]["hits"] == 1

    # 带过渡话的转人工规则：先回一句再暂停
    await admin_client.put(
        f"/api/v1/messages/rules/{r.json()['id']}",
        json={"keywords": ["发票"], "action": "handoff", "reply": "我确认一下马上回你"},
    )
    async with session_factory()() as s:
        conv = await s.get(Conversation, (await _conv(account_id)).id)
        conv.takeover_until = None
        await s.commit()
    await receive(account_id, chat("发票怎么开"))
    assert fake.sent[-1][2] == "我确认一下马上回你"
    assert (await _conv(account_id)).takeover_until is not None

    # 普通回复规则：内容和图片都没有时不允许保存
    bad = await admin_client.post("/api/v1/messages/rules", json={"keywords": ["x"], "reply": ""})
    assert bad.status_code == 422


async def test_account_default_bargain_applies_when_item_has_no_floor(admin_client, im):  # noqa: F811
    account_id, fake = im
    async with session_factory()() as s:
        from sqlalchemy import select

        item = (await s.execute(select(MyItem).where(MyItem.item_id == "900"))).scalar_one()
        item.floor_price = None
        await s.commit()
    llm = PriceEchoLLM()
    set_llm(LLMGateway(provider=llm))
    try:
        await receive(account_id, chat("能便宜点吗"))
        assert "议价决策" not in llm.prompts[-1]  # 没开默认议价：不让价

        await admin_client.patch(
            f"/api/v1/accounts/{account_id}",
            json={"settings": {"bargain_default": True, "bargain_max_percent": 10, "bargain_max_amount": 50}},
        )
        await receive(account_id, chat("800 行吗", cid="c2"))
        prompt = llm.prompts[-1]
        assert "议价决策" in prompt
        offer = float(prompt.split("报价=")[1].split("，")[0])
        assert 950 <= offer < 1000  # 最多让 min(10%, 50 元) = 50
    finally:
        set_llm(None)


def test_banned_words_fail_the_guardrail():
    assert not check_reply("比拼多多便宜", banned_words=("拼多多",)).ok
    assert check_reply("很便宜哦", banned_words=("拼多多",)).ok


def _mock_image_upload():
    return respx.post("https://stream-upload.goofish.com/api/upload.api").mock(
        return_value=httpx.Response(200, json={"object": {"url": IMG_URL, "pix": "800x600"}})
    )


@respx.mock
async def test_rule_reply_sends_images_and_they_are_not_seen_as_seller_takeover(admin_client, im):  # noqa: F811
    account_id, fake = im
    upload = _mock_image_upload()
    image_id = (await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()[
        "id"
    ]
    bad = await admin_client.post("/api/v1/messages/rules", json={"keywords": ["实拍"], "images": ["../../etc/passwd"]})
    assert bad.status_code == 422
    r = await admin_client.post(
        "/api/v1/messages/rules", json={"keywords": ["实拍"], "reply": "给你看实拍", "images": [image_id]}
    )
    assert r.status_code == 201
    await receive(account_id, chat("有实拍图吗"))
    assert fake.sent[-1][2] == "给你看实拍"
    assert fake.images == [("c1", BUYER, IMG_URL)]
    # 自己发出的图片回传过来：不算卖家亲自回复
    await receive(account_id, chat("[图片]", sender=SELLER))
    assert (await _conv(account_id)).takeover_until is None
    # 同一张图第二次发送不再重复上传
    await receive(account_id, chat("再发下实拍"))
    assert len(fake.images) == 2 and upload.call_count == 1


@respx.mock
async def test_delivery_sends_pool_images_after_text(admin_client, im):  # noqa: F811
    account_id, fake = im
    _mock_image_upload()
    mock_trade()
    image_id = (await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()[
        "id"
    ]
    await admin_client.patch(
        f"/api/v1/accounts/{account_id}", json={"settings": {"auto_delivery": True, "auto_reply": False}}
    )
    pool = await admin_client.post("/api/v1/cards/pools", json={"name": "二维码", "kind": "text", "images": [image_id]})
    assert pool.status_code == 201 and pool.json()["images"] == [image_id]
    await admin_client.post(
        "/api/v1/cards/bindings",
        json={"pool_id": pool.json()["id"], "item_id": "900", "template": "扫下面的二维码领取"},
    )
    await receive(account_id, chat("你好，我拍了"))
    await paid(account_id, "4400009")
    orders = (await admin_client.get("/api/v1/orders")).json()
    assert orders[0]["status"] == "delivered"
    assert fake.sent[-1][2] == "扫下面的二维码领取"
    assert fake.images == [("c1", BUYER, IMG_URL)]
