import json

import httpx
import respx

from app.domains.goods import service as goods_service
from app.domains.goods.ai_listing import ListingAI, build_knowledge, clean_listing_text, decide_pricing
from app.intelligence.llm import LLMGateway, LLMResult, set_llm
from app.intelligence.pricing import market_stats, suggest_price
from tests.test_goods import PNG, make_account

AI_OUT = {
    "titles": ["自用 AirPods Pro 2 九成新 带盒", "AirPods Pro 2 降噪耳机", "苹果耳机 Pro2"],
    "desc": "自用半年，功能正常，降噪效果好。左耳机有轻微划痕。需要的加我微信 abc123。保证正品，假一赔十！配件齐全。",
    "brand_model": "Apple AirPods Pro 2",
    "condition": "9成新",
    "category_hint": "耳机",
    "search_keyword": "airpods pro 2",
    "highlights": ["主动降噪"],
    "flaws": ["左耳机轻微划痕"],
    "accessories": ["充电盒", "数据线"],
    "is_virtual": False,
    "shipping_mode": "free",
    "post_fee": 0,
    "shipping_reason": "小件，包邮更好卖",
    "price_guess": 880,
    "orig_price_guess": 1899,
    "user_price": None,
    "user_floor": None,
    "faq": [{"q": "能小刀吗", "a": "诚心要可以小刀"}],
    "cover_index": 1,
    "uncertain": ["是否有购买发票"],
}


def ai(**over) -> ListingAI:
    return ListingAI.model_validate({**AI_OUT, **over})


def test_decide_pricing_priorities():
    sug = suggest_price(market_stats([700, 750, 800, 850, 900, 950]))
    # 1. 卖家说明里给的价格优先
    price, floor, orig, source, warns = decide_pricing(ai(user_price=1000, user_floor=900), sug, "market")
    assert (price, floor, orig) == (1000, 900, 1899) and "卖家" in source and not warns
    # 2. 同款行情 + 策略
    p_quick = decide_pricing(ai(), sug, "quick")[0]
    p_market, floor, *_ = decide_pricing(ai(), sug, "market")
    p_premium = decide_pricing(ai(), sug, "premium")[0]
    assert p_quick < p_market < p_premium and p_market == 825 and floor <= p_market
    # 3. 没有行情时用 AI 估价，并提醒确认
    price, floor, _, source, warns = decide_pricing(ai(), None, "market")
    assert price == 880 and floor == 748 and source == "AI 估价" and "AI 估计" in warns[0]
    # 4. 都没有 → 需要手填
    assert decide_pricing(ai(price_guess=None), None, "market")[0] is None
    # 最低价高于售价时忽略
    price, floor, _, _, warns = decide_pricing(ai(user_price=500, user_floor=600), None, "market")
    assert floor <= price and any("最低价" in w for w in warns)


def test_clean_listing_text_and_knowledge():
    text, removed = clean_listing_text(AI_OUT["desc"])
    assert "微信" not in text and "假一赔十" not in text and "左耳机有轻微划痕" in text
    assert len(removed) == 2
    kb = build_knowledge(ai())
    assert "左耳机轻微划痕" in kb and "Q：能小刀吗" in kb and "充电盒" in kb


@respx.mock
async def test_ai_draft_endpoint_regenerate_and_publish_guard(admin_client):
    acc_id = await make_account(admin_client)
    ids = [
        (await admin_client.post("/api/v1/goods/uploads", files={"file": (f"{i}.png", PNG, "image/png")})).json()["id"]
        for i in range(2)
    ]
    calls = []

    class Fake:
        async def complete(self, **kw):
            calls.append(kw)
            return LLMResult(text=json.dumps(outputs.pop(0), ensure_ascii=False), model="vision-model")

    outputs = [AI_OUT, {**AI_OUT, "price_guess": None, "search_keyword": ""}]
    set_llm(LLMGateway(provider=Fake()))
    goods_service._market_cache.clear()
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    rows = [
        {"data": {"item": {"main": {"exContent": {"itemId": str(i), "title": "airpods", "price": [{"text": str(p)}]}}}}}
        for i, p in enumerate([700, 750, 800, 850, 900, 950])
    ]
    respx.post(url__regex=r".*idlemtopsearch.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {"resultList": rows}})
    )

    r = await admin_client.post(
        "/api/v1/goods/ai-draft",
        json={"account_id": acc_id, "image_ids": ids, "hint": "自用半年", "strategy": "market"},
    )
    assert r.status_code == 201, r.text
    d = r.json()
    assert d["status"] == "draft" and d["price"] == 825 and d["floor_price"] <= 825 and d["orig_price"] == 1899
    assert d["title"] == AI_OUT["titles"][0] and "微信" not in d["desc"]
    assert d["image_ids"] == [ids[1], ids[0]]  # AI 选的封面放到第一张
    assert "Q：能小刀吗" in d["knowledge"] and d["shipping"] == "free"
    meta = d["ai_meta"]
    assert meta["uncertain"] == ["是否有购买发票"] and "同款行情" in meta["price_source"]
    assert any("自动删除" in w for w in meta["warnings"]) and meta["market"]["sample"] == 6
    assert len(calls[0]["images"]) == 2 and "自用半年" in calls[0]["messages"][0].content

    editable = {key: d[key] for key in ("account_id", "title", "desc", "image_ids", "price")}
    confirmed = await admin_client.put(
        f"/api/v1/goods/drafts/{d['id']}", json={**editable, "confirmed_facts": ["是否有购买发票"]}
    )
    assert confirmed.status_code == 200 and confirmed.json()["confirmed_facts"] == ["是否有购买发票"]

    # 重新生成：覆盖同一份草稿；无法估价时售价为 0，禁止直接发布
    r = await admin_client.post(
        "/api/v1/goods/ai-draft", json={"account_id": acc_id, "image_ids": ids, "draft_id": d["id"]}
    )
    assert r.status_code == 201 and r.json()["id"] == d["id"] and r.json()["price"] == 0
    assert r.json()["confirmed_facts"] == []
    assert "无法估价" in r.json()["ai_meta"]["warnings"][0]
    r = await admin_client.post(f"/api/v1/goods/drafts/{d['id']}/publish")
    assert r.status_code == 400 and "售价" in r.json()["detail"]

    # 卖家在确认页补全后保存，ai_meta 保留
    body = {k: r2 for k, r2 in (await admin_client.get("/api/v1/goods/drafts")).json()[0].items()}
    upd = {k: body[k] for k in ("account_id", "title", "desc", "image_ids", "knowledge", "shipping")}
    r = await admin_client.put(f"/api/v1/goods/drafts/{d['id']}", json={**upd, "price": 799, "floor_price": 700})
    assert r.status_code == 200 and r.json()["price"] == 799 and r.json()["ai_meta"]["model"] == "claude-opus-5-5"


async def test_ai_draft_without_llm(admin_client):
    acc_id = await make_account(admin_client)
    image_id = (await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()[
        "id"
    ]
    r = await admin_client.post("/api/v1/goods/ai-draft", json={"account_id": acc_id, "image_ids": [image_id]})
    assert r.status_code == 503


async def test_market_failure_is_reported_and_ai_guess_used():
    from app.domains.goods.ai_listing import generate_listing

    class Fake:
        async def complete(self, **kw):
            return LLMResult(text=json.dumps(AI_OUT, ensure_ascii=False), model="m")

    async def failing_lookup(_):
        raise RuntimeError("闲鱼风控保护中，暂停搜索")

    out = await generate_listing(
        LLMGateway(provider=Fake()),
        images=[("a", PNG, "image/png")],
        hint="",
        strategy="market",
        market_lookup=failing_lookup,
    )
    assert out.price == 880 and out.meta["price_source"] == "AI 估价"
    assert any("风控保护中" in w for w in out.meta["warnings"])


def test_ws_token_masked_in_access_log():
    import logging

    from app.core.logging import _AccessTokenFilter

    rec = logging.LogRecord(
        "uvicorn.access", 20, "", 0, '%s - "%s %s"', ("127.0.0.1", "WebSocket", "/api/v1/ws?token=abc.def.ghi"), None
    )
    _AccessTokenFilter().filter(rec)
    assert "abc.def" not in rec.getMessage() and "token=***" in rec.getMessage()


def test_strip_meta_sentences():
    from app.domains.goods.ai_listing import strip_meta_sentences

    text = "自用两年，电池 85%。因卖家未说明出售原因，文案不展开。具体以卖家确认为准。走闲鱼交易。"
    assert strip_meta_sentences(text) == "自用两年，电池 85%。走闲鱼交易。"
