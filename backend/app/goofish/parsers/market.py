"""商品搜索 / 详情 / 卖家主页响应解析。

字段路径来自对网页版接口的观察；接口变动时只需修改本文件并更新 tests/fixtures 中的样本。
"""

import json
import re
from typing import Any

from app.goofish.dto import (
    QUICK_FILTERS,
    ItemDetail,
    MarketItem,
    SearchPage,
    SearchQuery,
    SellerInfo,
    SellerProfile,
    SellerRating,
    TagIcon,
)
from app.goofish.parsers.common import dig, normalize_link, parse_int, parse_ms, parse_price

SORT_OPTIONS = {
    "newest": ("create", "desc"),
    "price_asc": ("price", "asc"),
    "price_desc": ("price", "desc"),
    "reduce": ("reduce", "desc"),
    "default": ("", ""),
}

# fishTags 图片标签的含义（用于文字标签与规则判断；展示直接用图标）
ICON_TEXT = {
    "freeShippingIcon": "包邮",
    "nfrIcon": "描述不符包邮退",
    "sevenIcon": "7天无理由",
}
_WANT_LABEL = "9"  # r3 里的“N人想要”，已有 want_cnt


_IP_KEYS = ("ipLocation", "ipAddress", "ipAddr", "ipProvince", "ipCity", "ipLoc")
_IP_TEXT = re.compile(r"IP\s*属地[:：\s]*([\u4e00-\u9fa5A-Za-z]+)")


def find_ip_location(data: Any, depth: int = 0) -> str:
    """在响应里查找 IP 属地：字段名在不同接口 / 版本中不固定，按已知键名和“IP属地：xx”文案兜底。"""
    if depth > 6:
        return ""
    if isinstance(data, dict):
        for key in _IP_KEYS:
            value = data.get(key)
            if isinstance(value, str) and value.strip():
                m = _IP_TEXT.search(value)
                return (m.group(1) if m else value).strip()
        for value in data.values():
            if found := find_ip_location(value, depth + 1):
                return found
    elif isinstance(data, list):
        for value in data[:50]:
            if found := find_ip_location(value, depth + 1):
                return found
    elif isinstance(data, str) and "属地" in data:
        m = _IP_TEXT.search(data)
        return m.group(1) if m else ""
    return ""


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
    quick += [f for f in q.quick_filters if f in QUICK_FILTERS and f not in quick]
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


def parse_fish_tags(fish_tags: dict[str, Any]) -> dict[str, Any]:
    """把搜索卡片的 fishTags 按行拆开：r1 标题前图标、r2 属性、r3 价格旁说明、r4 卖家标签、r5 服务图标。"""
    out: dict[str, Any] = {"tags": [], "attrs": [], "price_note": "", "seller_tags": [], "icons": []}
    for row in sorted(fish_tags):
        for tag in dig(fish_tags, row, "tagList", default=[]) or []:
            data = tag.get("data") or {}
            content = str(data.get("content") or "").strip()
            if not content:
                continue
            if data.get("type") == "img":
                if data.get("url"):
                    out["icons"].append(
                        TagIcon(
                            name=content,
                            url=str(data["url"]).replace("http://", "https://", 1),
                            row=row,
                            width=parse_int(data.get("width")),
                            height=parse_int(data.get("height")),
                        )
                    )
                text = ICON_TEXT.get(content)
                if text and text not in out["tags"]:
                    out["tags"].append(text)
            elif row == "r2":
                out["attrs"].append(content)
            elif row == "r3":
                if str(data.get("labelId")) != _WANT_LABEL and data.get("isStrikeThrough") != "true":
                    out["price_note"] = out["price_note"] or content
            elif row == "r4":
                out["seller_tags"].append(content)
            elif content not in out["tags"]:
                out["tags"].append(content)
    return out


def parse_search(data: dict[str, Any], page: int = 1) -> SearchPage:
    items: list[MarketItem] = []
    for row in dig(data, "resultList", default=[]) or []:
        main = dig(row, "data", "item", "main", default={})
        ex = main.get("exContent") or {}
        args = dig(main, "clickParam", "args", default={})
        item_id = str(ex.get("itemId") or args.get("item_id") or args.get("id") or "")
        if not item_id:
            continue
        cards = parse_fish_tags(ex.get("fishTags") or {})
        tags = cards.pop("tags")
        if args.get("tag") == "freeship" and "包邮" not in tags:
            tags.insert(0, "包邮")
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
                avatar=(ex.get("userAvatarUrl") or "").replace("http://", "https://", 1),
                **cards,
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
        ip_location=find_ip_location(seller_do),
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
        ip_location=find_ip_location(data.get("module") or data),
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
