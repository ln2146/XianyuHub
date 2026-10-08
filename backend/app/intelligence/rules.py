"""选品规则引擎（初筛）：硬条件过滤，不消耗大模型。"""

import re
from datetime import UTC, datetime, timedelta

from pydantic import BaseModel, Field

from app.goofish.dto import MarketItem

_ZHIMA_ORDER = ["信用较差", "信用中等", "信用良好", "信用优秀", "信用极好"]


class ItemRules(BaseModel):
    include_any: list[str] = Field(default_factory=list, description="标题至少包含其中一个（为空不限）")
    include_all: list[str] = Field(default_factory=list, description="标题必须全部包含")
    exclude: list[str] = Field(default_factory=list, description="标题/描述包含任一则排除")
    min_price: float | None = None
    max_price: float | None = None
    areas: list[str] = Field(default_factory=list, description="发货地包含其一（为空不限）")
    max_age_hours: int | None = Field(default=None, description="只要 N 小时内发布的")
    min_seller_zhima: str | None = Field(default=None, description="最低芝麻信用，如“信用良好”")
    min_seller_reg_days: int | None = None
    blacklist_sellers: list[str] = Field(default_factory=list)


def _norm(s: str) -> str:
    return re.sub(r"\s+", "", s).lower()


def _contains(text: str, word: str) -> bool:
    """text 为原文小写。纯字母数字按整词匹配（避免 "m1" 命中 "m12"），其余忽略空白做子串匹配。"""
    w = _norm(word)
    if re.fullmatch(r"[a-z0-9]+", w):
        return re.search(rf"(?<![a-z0-9]){re.escape(w)}(?![a-z0-9])", text) is not None
    return w in _norm(text)


def check_item(item: MarketItem, rules: ItemRules, *, zhima: str = "", reg_days: int | None = None) -> list[str]:
    """返回不满足的原因列表；为空表示通过。"""
    reasons: list[str] = []
    title = item.title.lower()
    full = f"{title} {item.desc.lower()}"
    if rules.include_any and not any(_contains(title, w) for w in rules.include_any):
        reasons.append("标题不含关键词")
    missing = [w for w in rules.include_all if not _contains(title, w)]
    if missing:
        reasons.append(f"标题缺少：{','.join(missing)}")
    hit = [w for w in rules.exclude if _contains(full, w)]
    if hit:
        reasons.append(f"命中排除词：{','.join(hit)}")
    if item.price is not None:
        if rules.min_price is not None and item.price < rules.min_price:
            reasons.append("低于最低价")
        if rules.max_price is not None and item.price > rules.max_price:
            reasons.append("高于最高价")
    if rules.areas and not any(a in (item.area or "") for a in rules.areas):
        reasons.append("地区不符")
    if rules.max_age_hours and item.publish_time:
        if datetime.now(UTC) - item.publish_time > timedelta(hours=rules.max_age_hours):
            reasons.append("发布时间过早")
    if item.seller_nick and item.seller_nick in rules.blacklist_sellers:
        reasons.append("卖家在黑名单")
    if rules.min_seller_zhima and zhima:
        try:
            if _ZHIMA_ORDER.index(zhima) < _ZHIMA_ORDER.index(rules.min_seller_zhima):
                reasons.append(f"卖家信用 {zhima} 不足")
        except ValueError:
            pass
    if rules.min_seller_reg_days and reg_days is not None and reg_days < rules.min_seller_reg_days:
        reasons.append("卖家账号太新")
    return reasons
