"""价格引擎：市场价分布、性价比评分、定价建议。买家判断“值不值”与卖家定价共用。"""

import statistics
from collections.abc import Sequence

from pydantic import BaseModel


class MarketStats(BaseModel):
    count: int
    min: float
    p25: float
    median: float
    p75: float
    max: float
    mean: float

    @classmethod
    def empty(cls) -> "MarketStats":
        return cls(count=0, min=0, p25=0, median=0, p75=0, max=0, mean=0)


class PriceSuggestion(BaseModel):
    quick_sale: float
    market: float
    premium: float
    basis: MarketStats


def _quantile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    pos = (len(sorted_vals) - 1) * q
    lo, hi = int(pos), min(int(pos) + 1, len(sorted_vals) - 1)
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo)


def market_stats(prices: Sequence[float | None], *, trim_outliers: bool = True) -> MarketStats:
    vals = sorted(float(p) for p in prices if p is not None and p > 0)
    if not vals:
        return MarketStats.empty()
    if trim_outliers and len(vals) >= 8:
        q1, q3 = _quantile(vals, 0.25), _quantile(vals, 0.75)
        iqr = q3 - q1
        # 一半以上样本同价（如电子资料大量挂 ¥1）时 IQR 为 0，按 1.5×IQR 会把所有不同的价格都当异常删掉、
        # 三档建议价因此全部相同；这时只去掉偏离中间价 10 倍以上的明显乱填价
        lo, hi = (q1 - 1.5 * iqr, q3 + 1.5 * iqr) if iqr > 0 else (q1 / 10, q3 * 10)
        trimmed = [v for v in vals if lo <= v <= hi]
        vals = trimmed or vals
    return MarketStats(
        count=len(vals),
        min=vals[0],
        p25=round(_quantile(vals, 0.25), 2),
        median=round(_quantile(vals, 0.5), 2),
        p75=round(_quantile(vals, 0.75), 2),
        max=vals[-1],
        mean=round(statistics.fmean(vals), 2),
    )


def deal_score(price: float | None, stats: MarketStats) -> int | None:
    """性价比评分 0~100：等于中位数为 50，越便宜越高；低于 P25 的一半时封顶。样本太少返回 None。"""
    if price is None or price <= 0 or stats.count < 5 or stats.median <= 0:
        return None
    ratio = price / stats.median
    score = 50 + (1 - ratio) * 100
    return max(0, min(100, int(round(score))))


def deal_label(score: int | None) -> str:
    if score is None:
        return "样本不足"
    if score >= 75:
        return "高性价比"
    if score >= 60:
        return "值得关注"
    if score >= 40:
        return "价格正常"
    return "价格偏高"


def suspicious_low(price: float | None, stats: MarketStats) -> bool:
    """价格远低于市场（< P25 的 50%）——常见于骗局 / 描述不符。"""
    return bool(price and stats.count >= 5 and price < stats.p25 * 0.5)


def suggest_price(stats: MarketStats) -> PriceSuggestion | None:
    if stats.count < 3:
        return None

    def r(v: float) -> float:
        return float(int(v)) if v >= 100 else round(v, 1)

    quick, market, premium = r(stats.p25 * 0.97), r(stats.median), r(stats.p75)
    # 同款挂牌价高度集中时三档会重合，给出有区别的选择：低价比参考价低 10%，高价高 20%
    if quick >= market:
        quick = r(market * 0.9)
    if premium <= market:
        premium = r(market * 1.2)
    return PriceSuggestion(quick_sale=quick, market=market, premium=premium, basis=stats)
