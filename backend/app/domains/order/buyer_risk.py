"""卖家视角的买家分析：该不该卖给他、要防什么（到手刀、仅退款、调包、站外交易…）。

信号来源（全部可追溯，不做地域等无依据的推断）：
1. 平台信用：主页上的“买家信用”等级。
2. 卖家给他的评价：他作为买家收到的评价里的差评与负面关键词（到手刀、仅退款、事多…）。
3. 当前聊天：买家发来的消息里的高危话术（先发货、收到再说、不满意就退、加微信、差评威胁…）。
4. 与本店的交易记录：在你名下账号的历史订单、退款次数、黑名单。
"""

import re
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.domains.buyer.analysis import keyword_hits
from app.goofish.dto import SellerProfile
from app.intelligence.llm import LLMGateway, Tier

# 卖家评价买家时常见的负面词；“到手刀”= 收货后以各种理由要求退部分款 / 压价
BUYER_NEGATIVE_WORDS = (
    "到手刀",
    "压价",
    "砍价",
    "仅退款",
    "退款",
    "退货",
    "恶意",
    "差评",
    "威胁",
    "事多",
    "事儿多",
    "墨迹",
    "磨叽",
    "不确认收货",
    "拖着",
    "调包",
    "掉包",
    "白嫖",
    "投诉",
    "小法庭",
    "不讲信用",
    "爽约",
    "放鸽子",
    "不付款",
    "找茬",
    "挑刺",
    "难缠",
    "骗子",
)
BUYER_POSITIVE_WORDS = (
    "爽快",
    "好买家",
    "痛快",
    "秒付",
    "好沟通",
    "靠谱",
    "诚信",
    "收货快",
    "确认收货快",
    "很好的买家",
)

_CREDIT_BONUS = {"极好": 10, "优秀": 6, "良好": 2, "中等": -6, "一般": -6, "较差": -20, "差": -20}


@dataclass(frozen=True)
class ChatRule:
    key: str
    label: str
    pattern: re.Pattern[str]
    penalty: int
    advice: str


# 买家聊天里的高危话术。命中前 3 个字里有否定词（不、没、别…）的不算
CHAT_RULES = (
    ChatRule(
        "off_platform",
        "引导站外沟通 / 付款",
        re.compile(r"微信|vx|v信|加v|威信|qq|支付宝转|私下(交易|转账|付)|线下(交易|转账)|不走(平台|闲鱼)", re.I),
        30,
        "一律拒绝，只在闲鱼内沟通和付款；站外交易出问题平台无法介入",
    ),
    ChatRule(
        "receive_first",
        "要求先发货 / 到手再付",
        re.compile(r"先发货|货到付款|到付|收到(货)?再(付|拍|说|补|谈|确认)|到手(再|后)(付|补|说|谈|看)"),
        20,
        "坚持买家在闲鱼付款后再发货",
    ),
    ChatRule(
        "refund_preset",
        "预设退款 / 退货条件",
        re.compile(r"不满意(就|直接)?退|有(问题|瑕疵)(就|直接|我就)?退|仅退款|退(一部分|点钱|差价)|部分退款"),
        15,
        "发货前录制完整打包视频，拍清序列号和已知瑕疵；描述里写明瑕疵",
    ),
    ChatRule(
        "threat",
        "以差评 / 投诉相要挟",
        re.compile(r"差评|投诉|举报|小法庭|曝光"),
        15,
        "保留聊天记录，必要时申请闲鱼客服或小法庭介入，不要私下妥协",
    ),
    ChatRule(
        "swap_risk",
        "要求先验货 / 不拆封退回（调包风险）",
        re.compile(r"(验|看)(一下|下)?(机|货)(再|才)(确认|收货|付)|拆(开|机)(看看|验)|序列号.{0,4}(发|给)我"),
        8,
        "贵重物品走验货宝；发货前记录序列号、IMEI 和特征，退货时逐项核对",
    ),
)
_CHAT_NEGATION = re.compile(r"(不|没|别|无|绝不|不会|不要)\S{0,1}$")


class ChatSignal(BaseModel):
    key: str
    label: str
    count: int
    evidence: list[str] = Field(default_factory=list)  # 原话节选
    advice: str = ""


class ShopHistory(BaseModel):
    orders: int = 0
    completed: int = 0
    refunded: int = 0  # 退款中 + 已退款
    closed: int = 0
    total_amount: float = 0.0
    blacklisted: bool = False
    blacklist_reason: str = ""


class RatingEvidence(BaseModel):
    content: str
    rate: int | None
    created_at: str = ""
    hits: list[str] = Field(default_factory=list)


class BuyerAnalysis(BaseModel):
    buyer_id: str
    nick: str = ""
    avatar: str = ""
    profile_error: str = ""  # 主页拉取失败的原因（其余信号仍然可用）
    buyer_credit: str = ""
    seller_credit: str = ""
    item_cnt: int | None = None
    rate_cnt: int | None = None
    # 他作为买家收到的评价（来自卖家）
    as_buyer: int = 0
    as_buyer_positive: int = 0
    as_buyer_negative: int = 0  # 中评 + 差评
    negative_hits: list[tuple[str, int]] = Field(default_factory=list)
    positive_hits: list[tuple[str, int]] = Field(default_factory=list)
    negative_reviews: list[RatingEvidence] = Field(default_factory=list)
    chat_signals: list[ChatSignal] = Field(default_factory=list)
    bargain_rounds: int = 0
    history: ShopHistory = Field(default_factory=ShopHistory)
    score: int = 0
    level: str = ""
    verdict: Literal["sell", "caution", "decline"] = "caution"
    highlights: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    precautions: list[str] = Field(default_factory=list)
    analyzed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


def chat_signals(messages: list[str]) -> list[ChatSignal]:
    """messages：买家发来的文字消息（不含系统消息）。"""
    out = []
    for rule in CHAT_RULES:
        evidence = []
        for text in messages:
            for m in rule.pattern.finditer(text):
                if _CHAT_NEGATION.search(text[max(0, m.start() - 4) : m.start()]):
                    continue
                evidence.append(text.strip()[:60])
                break
        if evidence:
            out.append(
                ChatSignal(
                    key=rule.key, label=rule.label, count=len(evidence), evidence=evidence[:3], advice=rule.advice
                )
            )
    return out


def analyze_buyer(
    buyer_id: str,
    profile: SellerProfile | None,
    *,
    messages: Sequence[str] = (),
    bargain_rounds: int = 0,
    history: ShopHistory | None = None,
    profile_error: str = "",
) -> BuyerAnalysis:
    a = BuyerAnalysis(buyer_id=buyer_id, profile_error=profile_error, bargain_rounds=bargain_rounds)
    a.history = history or ShopHistory()
    hi, risk, tips = a.highlights, a.risks, a.precautions
    score = 70

    # 1. 平台信用 + 卖家给他的评价
    if profile is not None:
        a.nick, a.avatar = profile.nick, profile.avatar
        a.buyer_credit, a.seller_credit = profile.buyer_credit, profile.seller_credit
        a.item_cnt, a.rate_cnt = profile.item_cnt, profile.rate_cnt
        for key, bonus in _CREDIT_BONUS.items():
            if key in profile.buyer_credit:
                score += bonus
                if bonus >= 6:
                    hi.append(profile.buyer_credit)
                elif bonus < 0:
                    risk.append(f"平台{profile.buyer_credit}")
                break

        from_sellers = [r for r in profile.ratings if "卖家" in r.role]
        a.as_buyer = len(from_sellers)
        a.as_buyer_positive = sum(1 for r in from_sellers if r.rate == 1)
        neg_counter: dict[str, int] = {}
        pos_counter: dict[str, int] = {}
        for r in from_sellers:
            neg = keyword_hits(r.content or "", BUYER_NEGATIVE_WORDS)
            for w in neg:
                neg_counter[w] = neg_counter.get(w, 0) + 1
            for w in keyword_hits(r.content or "", BUYER_POSITIVE_WORDS):
                pos_counter[w] = pos_counter.get(w, 0) + 1
            bad = r.rate is not None and r.rate < 1
            a.as_buyer_negative += int(bad)
            if bad or neg:
                a.negative_reviews.append(
                    RatingEvidence(content=(r.content or "")[:200], rate=r.rate, created_at=r.created_at, hits=neg)
                )
        a.negative_hits = sorted(neg_counter.items(), key=lambda x: -x[1])[:8]
        a.positive_hits = sorted(pos_counter.items(), key=lambda x: -x[1])[:6]
        a.negative_reviews = a.negative_reviews[:8]

        if a.as_buyer == 0:
            score -= 5
            risk.append("没有被卖家评价过（新买家或很少交易），无历史可参考")
        elif a.as_buyer < 3:
            score -= 2
            risk.append(f"作为买家仅被评价 {a.as_buyer} 次，参考价值有限")
        elif a.as_buyer >= 10 and a.as_buyer_positive / a.as_buyer >= 0.95:
            score += 6
            hi.append(f"卖家给他的好评率 {a.as_buyer_positive / a.as_buyer:.0%}（{a.as_buyer} 条）")
        if a.as_buyer_negative:
            score -= min(24, 8 * a.as_buyer_negative)
            risk.append(f"被卖家给过 {a.as_buyer_negative} 次中差评")
        if a.negative_hits:
            score -= min(24, 6 * len(a.negative_hits))
            risk.append("卖家评价里提到：" + "、".join(f"{w}×{n}" for w, n in a.negative_hits[:5]))
            if any(w in neg_counter for w in ("到手刀", "压价", "仅退款", "退款", "退货")):
                tips.append("历史上有收货后要求退款 / 压价的记录：发货前录制完整打包视频，拍清序列号和瑕疵")
        if a.positive_hits:
            hi.append("卖家常说他：" + "、".join(w for w, _ in a.positive_hits[:4]))
        if (profile.item_cnt or 0) >= 30:
            risk.append(f"本人也在卖 {profile.item_cnt} 件商品，可能是同行 / 倒卖，注意验货与调包")
    elif profile_error:
        risk.append(f"未能获取买家主页（{profile_error}），以下只基于聊天与本店记录")

    # 2. 当前聊天
    a.chat_signals = chat_signals(list(messages))
    chat_penalty = 0
    for sig in a.chat_signals:
        rule = next(r for r in CHAT_RULES if r.key == sig.key)
        chat_penalty += rule.penalty
        risk.append(f"聊天中出现「{sig.label}」：{sig.evidence[0]}")
        tips.append(sig.advice)
    score -= min(45, chat_penalty)
    if bargain_rounds >= 3:
        score -= 5
        risk.append(f"已反复议价 {bargain_rounds} 轮")

    # 3. 与本店的交易记录
    h = a.history
    if h.completed:
        score += min(10, 5 * h.completed)
        hi.append(f"老顾客：在你这里完成过 {h.completed} 笔交易")
    if h.refunded:
        score -= min(30, 15 * h.refunded)
        risk.append(f"在你这里有 {h.refunded} 笔退款记录")
    if h.blacklisted:
        score = min(score, 20)
        risk.insert(0, f"已在你的黑名单{'：' + h.blacklist_reason if h.blacklist_reason else ''}")

    a.score = max(0, min(100, score))
    if a.score >= 80:
        a.level, a.verdict = "放心卖", "sell"
    elif a.score >= 65:
        a.level, a.verdict = "正常交易", "sell"
    elif a.score >= 45:
        a.level, a.verdict = "谨慎交易", "caution"
    else:
        a.level, a.verdict = "建议不卖", "decline"
    if a.verdict != "sell" and not any("打包视频" in t for t in tips):
        tips.append("发货前录制完整打包视频，保留聊天记录，所有沟通和付款都在闲鱼内完成")
    a.precautions = list(dict.fromkeys(tips))
    return a


# ---------------------------------------------------------------- 大模型研判
class BuyerInsightOut(BaseModel):
    verdict: Literal["sell", "caution", "decline"]
    summary: str
    chat_assessment: str
    risk_points: list[str]
    precautions: list[str]
    suggested_reply: str


BUYER_INSIGHT_SYSTEM = """你是闲鱼卖家的交易风控顾问，帮卖家判断要不要把东西卖给这位买家，以及怎么防范。

重点识别：到手刀（收货后以各种理由要求退部分款 / 压价）、仅退款、恶意退货、调包、威胁差评、引导站外交易、要求先发货。
要求：
1. summary：2~3 句结论，说明主要依据。
2. chat_assessment：1~2 句点评聊天里的意图与话术（没有聊天就写“暂无聊天记录”）。
3. risk_points：具体风险点；precautions：可执行的防范措施（录像、序列号、验货宝、写明瑕疵、拒绝站外…）。
4. suggested_reply：一条可以直接发给买家的回复，礼貌但立场清楚（例如坚持平台交易、说明售后规则）。
只依据提供的数据，不要编造，不要以地域、性别等身份特征下结论；数据不足就直说。"""


async def buyer_insight(llm: LLMGateway, analysis: BuyerAnalysis, chat: list[dict[str, Any]]) -> BuyerInsightOut:
    data = analysis.model_dump(mode="json", exclude={"avatar", "analyzed_at"})
    lines = [f"[{'买家' if m['direction'] == 'in' else '我'}] {m['text'][:200]}" for m in chat[-40:] if m.get("text")]
    user = "# 规则分析结果\n" + str(data)[:5000] + "\n\n# 最近聊天（按时间顺序）\n" + ("\n".join(lines) or "（无）")
    return await llm.complete_json(
        Tier.CHAT, BUYER_INSIGHT_SYSTEM, user, BuyerInsightOut, max_tokens=1500, effort="low"
    )
