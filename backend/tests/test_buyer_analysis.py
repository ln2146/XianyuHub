from datetime import UTC, datetime, timedelta

import httpx
import respx

from app.core.db import session_factory
from app.domains.buyer.analysis import (
    PricePoint,
    analyze_item,
    analyze_seller,
    compare_ip,
    rating_dynamics,
    title_homogeneity,
    to_province,
)
from app.domains.buyer.models import MarketItemRecord
from app.goofish.dto import SellerProfile, SellerRating
from app.goofish.parsers.market import find_ip_location, parse_user_head
from app.intelligence.llm import LLMGateway, LLMResult, set_llm
from app.intelligence.pricing import market_stats
from tests.test_buyer import mock_market
from tests.test_goofish_protocol import load

NOW = datetime(2026, 10, 1, tzinfo=UTC)


def ms(days_ago: float) -> str:
    return str(int((NOW - timedelta(days=days_ago)).timestamp() * 1000))


def rating(rate: int, days_ago: float, content: str = "好评", role: str = "来自买家") -> SellerRating:
    return SellerRating(rate=rate, content=content, role=role, created_at=ms(days_ago))


def test_province_and_ip_compare():
    assert to_province("浙江省") == "浙江"
    assert to_province("杭州") == "浙江"
    assert to_province("广东 深圳") == "广东"
    assert to_province("某个小镇") is None
    assert compare_ip("浙江", "杭州")[0] == "match"
    assert compare_ip("IP属地：广东", "上海")[0] == "mismatch"
    assert compare_ip("美国", "上海")[0] == "overseas"
    assert compare_ip("", "上海")[0] == "unknown"
    assert compare_ip("浙江", "某个小镇")[0] == "unknown"


def test_find_ip_location():
    assert find_ip_location({"a": {"b": [{"ipLocation": "IP属地：江苏"}]}}) == "江苏"
    assert find_ip_location({"tags": [{"text": "IP属地：四川"}]}) == "四川"
    assert find_ip_location({"x": 1}) == ""
    head = {"module": {"base": {"displayName": "小王", "ipLocation": "上海"}}}
    assert parse_user_head("1", head).ip_location == "上海"


def test_rating_dynamics_trend_burst_and_keywords():
    ratings = [rating(1, 120 + i * 20) for i in range(10)]  # 早期全好评、分布均匀
    ratings += [rating(-1, 5, "描述不符，翻新机"), rating(-1, 10, "骗子"), rating(1, 20), rating(0, 25, "一般")]
    ratings.append(rating(1, 3, "作为买家很爽快", role="来自卖家"))  # 作为买家收到的评价不计入
    d = rating_dynamics(ratings, NOW)
    assert d.as_seller == 14 and d.negative == 2 and d.neutral == 1
    assert d.recent_30d == 4 and d.recent_90d == 4
    assert d.earlier_positive_rate == 1.0 and d.recent_positive_rate == 0.25
    assert d.trend == "down"
    assert dict(d.negative_hits)["不符"] == 1 and "骗" in dict(d.negative_hits)
    assert d.negatives[0].content.startswith("描述不符")
    assert len(d.monthly) == 10 and sum(b.negative for b in d.monthly) == 2
    assert d.monthly[0].month == "2025-12" and d.monthly[-1].month == "2026-09"  # 逐月连续，空月补 0
    assert not d.burst

    burst = rating_dynamics([rating(1, 1 + i * 0.5) for i in range(8)], NOW)
    assert burst.burst and "7 天" in burst.burst_note


def test_negative_hits_skip_negations():
    from app.domains.buyer.analysis import negative_hits

    assert negative_hits("屏幕也没有问题，无瑕疵") == []
    assert negative_hits("没有问题，但是电池有问题") == ["有问题"]
    assert negative_hits("描述不符，翻新机") == ["不符", "翻新"]


def test_few_reviews_and_listing_mismatch_lower_score():
    base = dict(item_area="上海", zhima="信用极好", reg_days=2000, now=NOW)
    many = SellerProfile(seller_id="1", ip_location="上海", ratings=[rating(1, 30 * i + 5) for i in range(12)])
    few = SellerProfile(seller_id="2", ip_location="上海", ratings=[rating(1, 5), rating(1, 40)])
    shop = SellerProfile(seller_id="3", ip_location="上海", item_cnt=79042, ratings=[rating(1, 5), rating(1, 40)])
    a, b, c = (analyze_seller(p, **base) for p in (many, few, shop))
    assert any("仅 2 条评价" in r for r in b.risks) and b.score < a.score
    assert any("成交记录与铺货规模不符" in r for r in c.risks) and c.score < b.score


def test_burst_uses_total_reviews_and_flags_revived_templated_accounts():
    week = [rating(1, 1 + i * 0.5, "好评9666666👍") for i in range(8)]
    # 高销量卖家：样本只有最新 8 条，但总评价 500 条，不算刷评
    assert not rating_dynamics(week, NOW, total=500).burst

    # 沉睡一年多的号突然集中获得模板化好评
    revived = rating_dynamics([*week, rating(1, 600), rating(1, 650)], NOW, total=10)
    assert revived.burst and revived.burst_count == 8 and revived.burst_revived
    assert revived.burst_templated == 1.0 and "沉寂半年以上" in revived.burst_note and "雷同" in revived.burst_note

    normal = SellerProfile(
        seller_id="1", ratings=[rating(1, 1 + i * 0.5, f"第{i}次买，卖家人很好发货快") for i in range(8)]
    )
    sleeper = SellerProfile(seller_id="2", ratings=[*week, rating(1, 600), rating(1, 650)], rate_cnt=10)
    n = analyze_seller(normal, reg_days=2000, now=NOW)
    z = analyze_seller(sleeper, reg_days=2000, now=NOW)
    assert n.ratings.burst and z.ratings.burst
    assert any("刷评养号" in r for r in z.risks) and z.score <= n.score - 10


def test_title_homogeneity():
    same = ["iPhone 13 128G 国行 95新"] * 3 + ["iPhone 13 256G 国行 99新"]
    mixed = ["自用 MacBook Air", "宜家书桌九成新", "Switch 健身环", "考研数学全套书"]
    assert title_homogeneity(same) > 0.5 > title_homogeneity(mixed)


def test_analyze_seller_dealer_vs_personal():
    dealer = SellerProfile(
        seller_id="9",
        introduction="专业回收批发，全国包邮",
        item_cnt=320,
        ip_location="广东",
        items=[{"title": f"iPhone 13 128G 国行 9{i}新", "price": 3000, "status": "在售"} for i in range(8)],
        ratings=[rating(1, 1 + i * 0.3) for i in range(10)],
    )
    a = analyze_seller(dealer, item_area="上海", zhima="信用良好", reg_days=90, sold_cnt=500, now=NOW)
    assert a.seller_type == "dealer" and a.ip_match == "mismatch"
    assert a.ratings.burst and a.level in ("谨慎", "高风险")
    assert any("IP 属地" in r for r in a.risks)

    personal = SellerProfile(
        seller_id="1",
        item_cnt=6,
        ip_location="上海",
        items=[{"title": t, "price": 1, "status": "在售"} for t in ("自用 MacBook Air", "宜家书桌", "Switch 健身环")],
        ratings=[rating(1, 30 * i + 5, "卖家很靠谱，描述一致") for i in range(12)],
    )
    b = analyze_seller(personal, item_area="上海", zhima="信用极好", reg_days=2000, now=NOW)
    assert b.seller_type == "personal" and b.ip_match == "match"
    assert b.level == "可信" and b.score > a.score
    assert any("靠谱" in h for h in b.highlights)


def test_analyze_item_price_position_and_risks():
    peers = [3000, 3100, 3200, 3300, 3400, 3500, 3600, 3700]
    stats = market_stats(peers)
    cheap = analyze_item(
        item_id="1",
        title="自用 MacBook Air M1",
        price=2700,
        orig_price=7999,
        want_cnt=30,
        browse_cnt=600,
        publish_time=NOW - timedelta(days=2),
        desc="自用一年，电池 92%，无拆修，有原盒和充电器，成色 95 新，换新机所以出。" * 2,
        images=["a", "b", "c", "d"],
        peers=peers,
        sample_source="keyword",
        snapshots=[PricePoint(price=2900, seen_at=NOW - timedelta(days=2)), PricePoint(price=2700, seen_at=NOW)],
        stats=stats,
        now=NOW,
    )
    assert cheap.percentile == 0 and cheap.diff_to_median is not None and cheap.diff_to_median < -0.15
    assert cheap.heat_level == "高" and cheap.price_change is not None and cheap.price_change < 0
    assert cheap.level == "值得入手" and not cheap.suspicious_low

    scam = analyze_item(
        item_id="2",
        title="MacBook Air",
        price=800,
        orig_price=None,
        want_cnt=0,
        browse_cnt=10,
        publish_time=NOW - timedelta(days=90),
        desc="加微信",
        images=[],
        peers=peers,
        sample_source="keyword",
        snapshots=[],
        stats=stats,
        now=NOW,
    )
    assert scam.suspicious_low and scam.level == "不建议"
    assert any("站外" in r for r in scam.risks) and any("实拍" in r for r in scam.risks)


def mock_seller(ip: str = "上海"):
    respx.post(url__regex=r".*user\.page\.head.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "ret": ["SUCCESS::ok"],
                "data": {
                    "module": {
                        "base": {"displayName": "数码小王", "introduction": "自用闲置", "ipLocation": ip},
                        "tabs": {"item": {"number": 5}, "rate": {"number": 3}},
                    }
                },
            },
        )
    )
    respx.post(url__regex=r".*xyh\.item\.list.*").mock(
        return_value=httpx.Response(
            200,
            json={
                "ret": ["SUCCESS::ok"],
                "data": {
                    "cardList": [{"cardData": {"id": 1, "title": "宜家书桌", "itemStatus": 0}}],
                    "nextPage": False,
                },
            },
        )
    )
    rates = [
        {"rate": 1, "feedback": "很靠谱", "gmtCreate": ms(3), "rateTagList": [{"text": "来自买家"}]},
        {"rate": -1, "feedback": "描述不符", "gmtCreate": ms(400), "rateTagList": [{"text": "来自买家"}]},
    ]
    return respx.post(url__regex=r".*trade\.rate\.list.*").mock(
        return_value=httpx.Response(
            200,
            json={"ret": ["SUCCESS::ok"], "data": {"cardList": [{"cardData": r} for r in rates], "nextPage": False}},
        )
    )


@respx.mock
async def test_item_and_seller_analysis_endpoints(admin_client):
    search = load("search_response.json")["data"]
    mock_market(search)
    rate_route = mock_seller()

    # 实时搜索结果进入市场商品库，详情补全描述与卖家信息
    assert (await admin_client.get("/api/v1/buyer/search?keyword=macbook")).status_code == 200
    assert (await admin_client.get("/api/v1/buyer/items/900000000001/detail")).status_code == 200

    r = await admin_client.get("/api/v1/buyer/items/900000000001/analysis?keyword=macbook")
    assert r.status_code == 200, r.text
    item = r.json()
    assert item["title"] and item["image_count"] == 2 and item["sample_source"] == "keyword"
    assert item["level"] and isinstance(item["risks"], list)

    r = await admin_client.get("/api/v1/buyer/items/900000000001/seller-analysis")
    assert r.status_code == 200, r.text
    seller = r.json()
    assert seller["ip_location"] == "上海" and seller["ip_match"] == "match"  # 发货地上海
    assert seller["zhima"] == "信用极好" and seller["ratings"]["as_seller"] == 2
    assert seller["ratings"]["recent_30d"] == 1 and seller["ratings"]["negatives"]

    # 24 小时内走缓存，不再请求卖家接口
    calls = rate_route.call_count
    assert (await admin_client.get("/api/v1/buyer/items/900000000001/seller-analysis")).status_code == 200
    assert rate_route.call_count == calls

    # 未配置大模型
    r = await admin_client.post("/api/v1/buyer/items/900000000001/insight", json={"keyword": "macbook"})
    assert r.status_code == 503


@respx.mock
async def test_item_insight_with_llm(admin_client):
    class FakeLLM:
        async def complete(self, **kw):
            assert "IP 属地" in kw["messages"][0].content
            return LLMResult(
                text='{"item_summary":"价格合理","seller_summary":"个人卖家","ip_assessment":"一致",'
                '"comment_insight":"口碑稳定","seller_type":"personal","trust_level":"high",'
                '"advice":"可以买","questions_for_seller":["电池多少？"]}',
                model="m",
            )

    set_llm(LLMGateway(provider=FakeLLM()))
    mock_market(load("search_response.json")["data"])
    mock_seller()
    r = await admin_client.post("/api/v1/buyer/items/900000000001/insight", json={})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ai"]["trust_level"] == "high" and body["seller"]["ip_match"] == "match"
    assert body["item"]["item_id"] == "900000000001"
    set_llm(None)


@respx.mock
async def test_seller_analysis_resolves_encrypted_seller_id(admin_client):
    # 搜索结果只给加密卖家 ID（含 / + =），卖家主页接口只认详情里的数字 ID
    search = load("search_response.json")["data"]
    for row in search["resultList"]:
        row["data"]["item"]["main"]["clickParam"]["args"]["seller_id"] = "/jf1vV4940xF+8ptf52jkAg=="
    mock_market(search)
    mock_seller()
    assert (await admin_client.get("/api/v1/buyer/search?keyword=macbook")).status_code == 200

    r = await admin_client.get("/api/v1/buyer/items/900000000001/seller-analysis")
    assert r.status_code == 200, r.text
    assert r.json()["seller_id"] == "2200001"

    # 再次搜索不会把数字 ID 覆盖回加密 ID
    assert (await admin_client.get("/api/v1/buyer/search?keyword=macbook")).status_code == 200
    async with session_factory()() as s:
        assert (await s.get(MarketItemRecord, "900000000001")).seller_id == "2200001"
