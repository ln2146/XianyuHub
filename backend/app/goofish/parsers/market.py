"""商品搜索 / 详情 / 卖家主页响应解析。

字段路径来自对网页版接口的观察；接口变动时只需修改本文件并更新 tests/fixtures 中的样本。
"""

import json
from typing import Any

from app.goofish.dto import (
    ItemDetail,
    MarketItem,
    SearchPage,
    SearchQuery,
    SellerInfo,
    SellerProfile,
    SellerRating,
)
from app.goofish.parsers.common import dig, normalize_link, parse_int, parse_ms, parse_price

SORT_OPTIONS = {
    "newest": ("create", "desc"),
    "price_asc": ("price", "asc"),
    "price_desc": ("price", "desc"),
    "default": ("", ""),
}


def build_search_payload(q: SearchQuery) -> dict[str, Any]:
    """构造 mtop.taobao.idlemtopsearch.pc.search 请求体：筛选全部走参数，不依赖页面 DOM。"""
    sort_field, sort_value = SORT_OPTIONS.get(q.sort, SORT_OPTIONS["newest"])
    filters: list[str] = []
    if q.min_price is not None or q.max_price is not None:
        filters.append(f"priceRange:{q.min_price or 0},{q.max_price if q.max_price is not None else 99999999}")
    if q.publish_days:
        filters.append(f"publishDays:{q.publish_days}")
    quick = [
        name for flag, name in ((q.personal_only, "filterPersonal"), (q.free_shipping, "filterFreePostage")) if flag
    ]
    if quick:
        filters.append("quickFilter:" + ",".join(quick))
    extra = "{}"
    if q.province or q.city:
        extra = json.dumps(
            {
                "divisionList": [{"province": q.province or "", "city": q.city or ""}],
                "excludeMultiPlacesSellers": "0",
                "extraDivision": "",
            },
            separators=(",", ":"),
            ensure_ascii=False,
        )
    return {
        "pageNumber": q.page,
        "keyword": q.keyword,
        "fromFilter": bool(filters) or q.sort != "default" or extra != "{}",
        "rowsPerPage": 30,
        "sortValue": sort_value,
        "sortField": sort_field,
        "customDistance": "",
        "gps": "",
        "propValueStr": {"searchFilter": (";".join(filters) + ";") if filters else ""},
        "customGps": "",
        "searchReqFromPage": "pcSearch",
        "extraFilterValue": extra,
        "userPositionJson": "{}",
    }


def parse_search(data: dict[str, Any], page: int = 1) -> SearchPage:
    items: list[MarketItem] = []
    for row in dig(data, "resultList", default=[]) or []:
        main = dig(row, "data", "item", "main", default={})
        ex = main.get("exContent") or {}
        args = dig(main, "clickParam", "args", default={})
        item_id = str(ex.get("itemId") or args.get("item_id") or args.get("id") or "")
        if not item_id:
            continue
        tags: list[str] = []
        if args.get("tag") == "freeship":
            tags.append("包邮")
        for tag in dig(ex, "fishTags", "r1", "tagList", default=[]) or []:
            content = dig(tag, "data", "content", default="")
            if content and content not in tags:
                tags.append(content)
        price_raw = ex.get("price")
        price_text = (
            "".join(str(p.get("text", "")) for p in price_raw if isinstance(p, dict))
            if isinstance(price_raw, list)
            else str(price_raw or "")
        ).replace("当前价", "")
        items.append(
            MarketItem(
                item_id=item_id,
                title=ex.get("title") or "",
                price=parse_price(price_raw),
                price_text=price_text.strip(),
                orig_price=parse_price(ex.get("oriPrice")),
                want_cnt=parse_int(args.get("wantNum")),
                area=ex.get("area") or "",
                seller_nick=ex.get("userNickName") or "",
                seller_id=str(args.get("seller_id") or ex.get("userId") or "") or None,
                image_url=ex.get("picUrl") or "",
                images=[ex["picUrl"]] if ex.get("picUrl") else [],
                publish_time=parse_ms(args.get("publishTime")),
                link=normalize_link(main.get("targetUrl"), item_id),
                tags=tags,
            )
        )
    has_more = bool(dig(data, "resultInfo", "hasNextPage", default=len(items) >= 30))
    return SearchPage(items=items, page=page, has_more=has_more)


def parse_detail(data: dict[str, Any]) -> ItemDetail:
    item_do = data.get("itemDO") or {}
    seller_do = data.get("sellerDO") or {}
    item_id = str(item_do.get("itemId") or "")
    images = [img.get("url") for img in item_do.get("imageInfos") or [] if isinstance(img, dict) and img.get("url")]
    item = MarketItem(
        item_id=item_id,
        title=item_do.get("title") or "",
        price=parse_price(item_do.get("soldPrice") or item_do.get("price")),
        price_text=str(item_do.get("soldPrice") or ""),
        orig_price=parse_price(item_do.get("originalPrice")),
        want_cnt=parse_int(item_do.get("wantCnt")),
        browse_cnt=parse_int(item_do.get("browseCnt")),
        area=seller_do.get("publishCity") or seller_do.get("city") or "",
        seller_nick=seller_do.get("nick") or "",
        seller_id=str(seller_do.get("sellerId") or "") or None,
        image_url=images[0] if images else "",
        images=images,
        publish_time=parse_ms(item_do.get("gmtCreate")),
        link=normalize_link(None, item_id),
        desc=item_do.get("desc") or "",
    )
    seller = SellerInfo(
        seller_id=item.seller_id,
        nick=item.seller_nick,
        zhima_level=dig(seller_do, "zhimaLevelInfo", "levelName", default="") or "",
        reg_days=parse_int(seller_do.get("userRegDay")),
        sold_cnt=parse_int(seller_do.get("hasSoldNumInteger")),
    )
    status = str(item_do.get("itemStatusStr") or item_do.get("itemStatus") or "")
    return ItemDetail(item=item, seller=seller, status=status, raw=data)


def parse_user_head(seller_id: str, data: dict[str, Any]) -> SellerProfile:
    base = dig(data, "module", "base", default={})
    seller_credit = buyer_credit = ""
    for tag in base.get("ylzTags") or []:
        role = dig(tag, "attributes", "role")
        if role == "seller":
            seller_credit = tag.get("text") or ""
        elif role == "buyer":
            buyer_credit = tag.get("text") or ""
    return SellerProfile(
        seller_id=seller_id,
        nick=base.get("displayName") or "",
        avatar=dig(base, "avatar", "avatar", default="") or "",
        introduction=base.get("introduction") or "",
        item_cnt=parse_int(dig(data, "module", "tabs", "item", "number")),
        rate_cnt=parse_int(dig(data, "module", "tabs", "rate", "number")),
        seller_credit=seller_credit,
        buyer_credit=buyer_credit,
    )


def parse_user_items(data: dict[str, Any]) -> tuple[list[dict[str, Any]], bool]:
    rows = []
    for card in data.get("cardList") or []:
        d = card.get("cardData") or {}
        status = d.get("itemStatus")
        rows.append(
            {
                "item_id": str(d.get("id") or ""),
                "title": d.get("title") or "",
                "price": parse_price(dig(d, "priceInfo", "price")),
                "image_url": dig(d, "picInfo", "picUrl", default=""),
                "status": "在售" if status == 0 else "已售" if status == 1 else str(status),
            }
        )
    return rows, bool(data.get("nextPage"))


def parse_ratings(data: dict[str, Any]) -> tuple[list[SellerRating], bool]:
    out = []
    for card in data.get("cardList") or []:
        d = card.get("cardData") or {}
        out.append(
            SellerRating(
                rate_id=str(d.get("rateId") or "") or None,
                content=d.get("feedback") or "",
                rate=d.get("rate"),
                role=dig(d, "rateTagList", 0, "text", default="") or "",
                rater_nick=d.get("raterUserNick") or "",
                created_at=str(d.get("gmtCreate") or ""),
            )
        )
    return out, bool(data.get("nextPage"))
