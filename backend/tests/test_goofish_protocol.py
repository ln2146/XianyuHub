import base64
import hashlib
import json
from pathlib import Path

import httpx
import msgpack
import pytest
import respx

from app.goofish.dto import ImEventType, SearchQuery, SystemNotice
from app.goofish.errors import BizError, RiskControlError, SessionExpiredError, TokenExpiredError
from app.goofish.parsers.common import parse_price
from app.goofish.parsers.im import classify_notice, extract_order_id, parse_message
from app.goofish.parsers.market import build_search_payload, parse_detail, parse_fish_tags, parse_search
from app.goofish.protocol.codec import decode_push_data, encode_custom
from app.goofish.protocol.cookies import (
    h5_token,
    is_logged_in,
    merge_cookies,
    parse_cookie_str,
    parse_set_cookie,
)
from app.goofish.protocol.mtop import MtopClient, classify_ret
from app.goofish.protocol.sign import gen_device_id, gen_mid, mtop_sign

FIX = Path(__file__).parent / "fixtures"


def load(name: str) -> dict:
    return json.loads((FIX / name).read_text("utf-8"))


# ---------------------------------------------------------------- sign / cookies
def test_mtop_sign_matches_md5_formula():
    expected = hashlib.md5(b"abc&1700000000000&34839810&{}").hexdigest()
    assert mtop_sign("abc", 1700000000000, "{}") == expected


def test_ids():
    assert gen_mid().endswith(" 0")
    assert gen_device_id("2200").endswith("-2200")


def test_cookie_helpers():
    c = parse_cookie_str("unb=1; cookie2=x; _m_h5_tk=tok123_1700; bad; =v")
    assert c == {"unb": "1", "cookie2": "x", "_m_h5_tk": "tok123_1700"}
    assert h5_token(c) == "tok123"
    assert is_logged_in(c)
    updates = parse_set_cookie(
        ["_m_h5_tk=new_1; Path=/; Domain=.goofish.com", "old=; Expires=Thu, 01-Jan-1970 00:00:00 GMT"]
    )
    c["old"] = "1"
    assert merge_cookies(c, updates)
    assert c["_m_h5_tk"] == "new_1" and "old" not in c


@pytest.mark.parametrize(
    "ret,exc",
    [
        (["FAIL_SYS_TOKEN_EXOIRED::令牌过期"], TokenExpiredError),
        (["FAIL_SYS_SESSION_EXPIRED::Session过期"], SessionExpiredError),
        (["FAIL_SYS_USER_VALIDATE"], RiskControlError),
        (["RGV587_ERROR::SM::哎哟喂,被挤爆啦,请稍后重试"], RiskControlError),
        (["FAIL_BIZ_ITEM_NOT_EXIST::商品不存在"], BizError),
    ],
)
def test_classify_ret(ret, exc):
    with pytest.raises(exc):
        classify_ret(ret, {}, "api")
    classify_ret(["SUCCESS::调用成功"], {}, "api")


def test_classify_ret_carries_punish_url():
    with pytest.raises(RiskControlError) as ei:
        classify_ret(["FAIL_SYS_USER_VALIDATE"], {"url": "https://x/punish?x5secdata=1"}, "api")
    assert ei.value.punish_url.endswith("x5secdata=1")


# ---------------------------------------------------------------- mtop client
@respx.mock
async def test_mtop_client_retries_after_token_refresh():
    calls = []

    def handler(request: httpx.Request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"ret": ["FAIL_SYS_TOKEN_EMPTY::令牌为空"], "data": {}},
                headers=[("set-cookie", "_m_h5_tk=fresh_999; Path=/"), ("set-cookie", "_m_h5_tk_enc=e; Path=/")],
            )
        return httpx.Response(200, json={"ret": ["SUCCESS::调用成功"], "data": {"ok": 1}})

    respx.post(url__regex=r"https://h5api\.m\.goofish\.com/h5/mtop\.test/1\.0/.*").mock(side_effect=handler)
    updated = []
    async with MtopClient({}, on_cookies_updated=lambda c: updated.append(c)) as client:
        data = await client.call("mtop.test", {"a": 1})
    assert data == {"ok": 1}
    assert len(calls) == 2
    # 第二次请求使用新 token 签名
    second = calls[1]
    t = second.url.params["t"]
    assert second.url.params["sign"] == mtop_sign("fresh", t, '{"a":1}')
    assert updated and updated[-1]["_m_h5_tk"] == "fresh_999"


@respx.mock
async def test_mtop_client_risk_detection_on_html():
    respx.post(url__regex=r".*mtop\.risky.*").mock(
        return_value=httpx.Response(200, text="<html>punish x5secdata</html>")
    )
    async with MtopClient({"_m_h5_tk": "a_1"}) as client:
        with pytest.raises(RiskControlError):
            await client.call("mtop.risky", {})


# ---------------------------------------------------------------- market parsers
def test_build_search_payload_filters():
    p = build_search_payload(
        SearchQuery(
            keyword="macbook",
            min_price=1000,
            max_price=4000,
            publish_days=7,
            province="上海",
            city="上海",
            personal_only=True,
            free_shipping=True,
        )
    )
    assert p["propValueStr"]["searchFilter"] == (
        "priceRange:1000,4000;publishDays:7;quickFilter:filterPersonal,filterFreePostage;"
    )
    assert json.loads(p["extraFilterValue"])["divisionList"][0]["city"] == "上海"
    assert p["sortField"] == "create" and p["fromFilter"] is True


def test_build_search_payload_quick_filters_and_reduce_sort():
    p = build_search_payload(
        SearchQuery(
            keyword="iphone",
            sort="reduce",
            personal_only=True,
            quick_filters=["filterAppraise", "filterPersonal", "inspectedPhone", "bogus"],
        )
    )
    # 与 goofish.com 抓包一致；重复项与未知项被丢弃
    assert p["propValueStr"]["searchFilter"] == "quickFilter:filterPersonal,filterAppraise,inspectedPhone;"
    assert (p["sortField"], p["sortValue"]) == ("reduce", "desc")


def test_parse_fish_tags_rows():
    # 结构取自 goofish.com 搜索接口的真实响应（节选）
    def img(content, url="http://gw.alicdn.com/x.png"):
        return {"data": {"type": "img", "content": content, "url": url, "width": "76", "height": "14"}}

    def text(content, **kw):
        return {"data": {"type": "gradientImageText", "content": content, **kw}}

    out = parse_fish_tags(
        {
            "r1": {"tagList": [img("freeShippingIcon")]},
            "r2": {"tagList": [text("几乎全新"), text("Apple/苹果"), text("256GB")]},
            "r3": {
                "tagList": [
                    text("¥8999", isStrikeThrough="true", labelId="41"),
                    text("累计降价168.00元", labelId="749"),
                    text("6人想要", labelId="9"),
                ]
            },
            "r4": {"tagList": [text("卖家信用优秀", labelId="919")]},
            "r5": {"tagList": [img("nfrIcon"), img("sevenIcon")]},
        }
    )
    assert out["attrs"] == ["几乎全新", "Apple/苹果", "256GB"]
    assert out["price_note"] == "累计降价168.00元"
    assert out["seller_tags"] == ["卖家信用优秀"]
    assert out["tags"] == ["包邮", "描述不符包邮退", "7天无理由"]  # 不再混入 freeShippingIcon 这类图标名
    assert [i.name for i in out["icons"]] == ["freeShippingIcon", "nfrIcon", "sevenIcon"]
    assert out["icons"][0].url.startswith("https://") and out["icons"][0].width == 76
    assert [i.row for i in out["icons"]] == ["r1", "r5", "r5"]


def test_parse_search():
    page = parse_search(load("search_response.json")["data"])
    assert len(page.items) == 2 and page.has_more
    a, b = page.items
    assert a.item_id == "900000000001" and a.price == 3200 and a.orig_price == 7999
    assert a.want_cnt == 12 and a.seller_id == "2200001"
    assert a.tags == ["包邮", "验货宝"]
    assert a.link == "https://www.goofish.com/item?id=900000000001"
    assert a.publish_time is not None
    assert b.price == 12000 and b.link.endswith("900000000002")


def test_parse_detail():
    d = parse_detail(load("detail_response.json")["data"])
    assert d.item.desc.startswith("自用一年")
    assert len(d.item.images) == 2 and d.item.browse_cnt == 356
    assert d.seller.zhima_level == "信用极好" and d.seller.reg_days == 1460


@pytest.mark.parametrize("raw,val", [("¥1,299", 1299), ("1.5万", 15000), (None, None), ("面议", None), (88, 88)])
def test_parse_price(raw, val):
    assert parse_price(raw) == val


# ---------------------------------------------------------------- IM codec / parser
def _pack(obj) -> str:
    return base64.b64encode(msgpack.packb(obj)).decode()


def test_codec_msgpack_and_json():
    msg = {1: {2: "55@goofish", 10: {"reminderContent": "在吗"}}}
    kind, obj = decode_push_data(_pack(msg))
    assert kind == "msgpack" and obj["1"]["2"] == "55@goofish"
    kind, obj = decode_push_data(base64.b64encode(b'{"a":1}').decode())
    assert kind == "json" and obj == {"a": 1}
    assert json.loads(base64.b64decode(encode_custom({"x": "中文"}))) == {"x": "中文"}


def chat_message(text: str, extra: dict | None = None) -> dict:
    body = {
        "2": "50001@goofish",
        "5": 1759900000000,
        "10": {
            "reminderContent": text,
            "reminderTitle": "买家A",
            "senderUserId": "3300",
            "reminderUrl": "https://www.goofish.com/im?itemId=900000000001&peerUserId=3300",
        },
    }
    body.update(extra or {})
    return {"1": body}


def test_parse_chat_message():
    ev = parse_message(chat_message("还在吗？能便宜点吗"))
    assert ev.type == ImEventType.CHAT and not ev.is_system
    assert ev.cid == "50001" and ev.sender_id == "3300" and ev.item_id == "900000000001"


def test_parse_paid_system_message_with_order_id():
    card = json.dumps({"dxCard": {"item": {"main": {"targetUrl": "fleamarket://order_detail?id=4400123456789"}}}})
    ev = parse_message(chat_message("[我已付款，等待你发货]", {"6": {"3": {"5": card}}}))
    assert ev.is_system and ev.notice == SystemNotice.PAID
    assert ev.order_id == "4400123456789"


def test_parse_order_status_and_typing():
    ev = parse_message({"1": "3300@goofish", "3": {"redReminder": "等待卖家发货"}, "x": "orderId=5500000001"})
    assert ev.type == ImEventType.ORDER and ev.sender_id == "3300"
    assert ev.order_id == "5500000001"
    ev = parse_message({"1": [{"1": "3300@goofish"}]})
    assert ev.type == ImEventType.TYPING


def test_classify_notice():
    assert classify_notice("[我已拍下，待付款]") == SystemNotice.ORDER_CREATED
    assert classify_notice("[记得及时发货]") == SystemNotice.PAID
    assert classify_notice("普通聊天") == SystemNotice.NONE
    assert extract_order_id("nothing here") is None


@respx.mock
async def test_ensure_token_tolerates_biz_error_on_bootstrap():
    """2026-10：取令牌的接口在重试时报“缺少业务参数 piUrl”，但令牌已经通过 Set-Cookie 下发。"""
    calls = []

    def handler(request):
        calls.append(request)
        if len(calls) == 1:
            return httpx.Response(
                200,
                json={"ret": ["FAIL_SYS_TOKEN_EMPTY::令牌为空"], "data": {}},
                headers={"set-cookie": "_m_h5_tk=t1_9"},
            )
        return httpx.Response(200, json={"ret": ["FAIL_SYS_BIZPARAM_MISSED::缺少业务参数piUrl"], "data": {}})

    respx.post(url__regex=r".*mtop\.gaia.*").mock(side_effect=handler)
    async with MtopClient({}) as client:
        await client.ensure_token()
        assert h5_token(client.cookies) == "t1"


@respx.mock
async def test_ensure_token_still_raises_on_risk():
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["RGV587_ERROR::SM::被挤爆啦"], "data": {}})
    )
    async with MtopClient({}) as client:
        with pytest.raises(RiskControlError):
            await client.ensure_token()
