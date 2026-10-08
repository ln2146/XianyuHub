"""议价策略引擎：价格完全由代码决定，LLM 只拿到结构化结果去组织语言。

规则：
1. 买家出价 ≥ 标价 × accept_ratio → 直接同意
2. 已达到最大轮次 → 报最终价 max(底价, 上次报价)，不再让
3. 本轮让价 step = (标价 − 底价) × step_ratios[n]；商品热度高时让价减半
4. 本轮报价 offer = max(底价, 上次报价 − step)；买家出价 ≥ offer → 按买家出价成交
5. 买家出价 < 底价 × 0.6 视为“砍得太狠”，礼貌拒绝并报本轮价
"""

import math
import re
from dataclasses import dataclass, field
from enum import StrEnum

from pydantic import BaseModel, Field


class BargainPolicy(BaseModel):
    list_price: float = Field(gt=0)
    floor_price: float = Field(gt=0)
    max_rounds: int = Field(default=3, ge=0, le=10)
    step_ratios: list[float] = Field(default_factory=lambda: [0.4, 0.3, 0.2, 0.1])
    accept_ratio: float = 0.98
    gifts: str = ""
    hot_want_threshold: int = 10  # 想要人数超过该值视为热门，让价减半
    round_to: float = 1.0  # 报价取整单位

    def model_post_init(self, _ctx) -> None:  # noqa: ANN001
        if self.floor_price > self.list_price:
            raise ValueError("底价不能高于标价")


class BargainAction(StrEnum):
    ACCEPT = "accept"  # 同意买家出价
    COUNTER = "counter"  # 还价
    FINAL = "final"  # 最终价，不再让
    TOO_LOW = "too_low"  # 砍太狠
    NO_OFFER = "no_offer"  # 买家只问“能便宜吗”，没有给出价格


@dataclass
class BargainState:
    rounds: int = 0
    last_offer: float | None = None


@dataclass
class BargainDecision:
    action: BargainAction
    offer: float  # 本轮我方可接受价格（同意时等于成交价）
    is_final: bool
    buyer_offer: float | None
    rounds_after: int
    gifts: str = ""
    notes: list[str] = field(default_factory=list)

    def for_llm(self) -> dict:
        """交给 LLM 的结构化信息（不包含底价）。"""
        return {
            "action": self.action.value,
            "price": self.offer,
            "is_final": self.is_final,
            "buyer_offer": self.buyer_offer,
            "gifts": self.gifts,
        }


_OFFER = re.compile(r"(\d+(?:\.\d+)?)\s*(元|块|米|w|万|k)?", re.IGNORECASE)
_OFFER_HINT = re.compile(r"(元|块|米|出|给|收|能不能|行不行|可以吗|可不可以|包邮|最多|最低|少|便宜)")


def extract_buyer_offer(text: str, list_price: float) -> float | None:
    """从买家消息中提取出价。只接受在标价 10%~120% 区间内、带价格语境的数字。"""
    candidates = []
    for m in _OFFER.finditer(text):
        value = float(m.group(1))
        unit = (m.group(2) or "").lower()
        if unit in ("w", "万"):
            value *= 10000
        elif unit == "k":
            value *= 1000
        context = text[max(0, m.start() - 4) : m.end() + 4]
        if not (unit or _OFFER_HINT.search(context)):
            continue
        if list_price * 0.1 <= value <= list_price * 1.2:
            candidates.append(value)
    return candidates[-1] if candidates else None


def _round(value: float, unit: float, floor: float) -> float:
    """按 unit 取整，且结果永远不低于底价（低于时向上取整）。"""
    if unit <= 0:
        return max(round(value, 2), floor)
    rounded = float(int(value / unit + 0.5) * unit)
    if rounded < floor:
        rounded = float(math.ceil(floor / unit) * unit)
    return rounded


def decide(
    policy: BargainPolicy,
    state: BargainState,
    buyer_text: str,
    *,
    want_cnt: int | None = None,
) -> BargainDecision:
    p = policy
    buyer_offer = extract_buyer_offer(buyer_text, p.list_price)
    last = state.last_offer if state.last_offer is not None else p.list_price
    hot = want_cnt is not None and want_cnt >= p.hot_want_threshold
    notes: list[str] = []

    if buyer_offer is not None and buyer_offer >= max(p.floor_price, p.list_price * p.accept_ratio):
        return BargainDecision(BargainAction.ACCEPT, buyer_offer, True, buyer_offer, state.rounds, notes=["接近标价"])

    if state.rounds >= p.max_rounds:
        final = _round(max(p.floor_price, last), p.round_to, p.floor_price)
        if buyer_offer is not None and buyer_offer >= final:
            return BargainDecision(BargainAction.ACCEPT, buyer_offer, True, buyer_offer, state.rounds)
        return BargainDecision(BargainAction.FINAL, final, True, buyer_offer, state.rounds, p.gifts, ["已达最大轮次"])

    ratio = p.step_ratios[min(state.rounds, len(p.step_ratios) - 1)] if p.step_ratios else 0
    step = (p.list_price - p.floor_price) * ratio
    if hot:
        step *= 0.5
        notes.append("热门商品，让价减半")
    offer = _round(max(p.floor_price, last - step), p.round_to, p.floor_price)
    rounds_after = state.rounds + 1
    is_final = offer - p.floor_price < max(p.round_to, 0.01) or rounds_after >= p.max_rounds

    if buyer_offer is not None and buyer_offer >= offer:
        return BargainDecision(BargainAction.ACCEPT, buyer_offer, True, buyer_offer, rounds_after, notes=notes)
    if buyer_offer is not None and buyer_offer < p.floor_price * 0.6:
        return BargainDecision(BargainAction.TOO_LOW, offer, is_final, buyer_offer, rounds_after, p.gifts, notes)
    action = BargainAction.FINAL if is_final else BargainAction.COUNTER
    if buyer_offer is None:
        action = BargainAction.NO_OFFER if not is_final else BargainAction.FINAL
    return BargainDecision(action, offer, is_final, buyer_offer, rounds_after, p.gifts, notes)


def template_reply(d: BargainDecision) -> str:
    """LLM 不可用或输出被护栏拦截时的兜底话术。"""
    price = f"{d.offer:g}"
    if d.action == BargainAction.ACCEPT:
        return f"可以的，{price}出给你，直接拍下我改价～"
    if d.action == BargainAction.FINAL:
        return f"最低{price}了，真的不能再少啦" + (f"，可以送{d.gifts}" if d.gifts else "")
    if d.action == BargainAction.TOO_LOW:
        return f"这个价格太低了哈，{price}可以考虑"
    return f"诚心要的话{price}可以出" + (f"，再送{d.gifts}" if d.gifts else "")
