"""AI 生成发布草稿：卖家只需上传图片（可附一句说明），其余由 AI + 规则生成，卖家确认后发布。

分工：
- 大模型：看图识别商品，写标题 / 描述，判断成色、瑕疵、配件、运费方式，生成客服知识库，
  并从卖家说明里提取其明确给出的价格
- 代码：根据同款行情和定价策略计算售价、底价（AI 只在缺少行情时给估价，且会提示卖家确认），
  清洗描述中的站外联系方式 / 承诺性表述，挑选封面图
"""

import math
import re
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.intelligence.guardrails import OFF_PLATFORM_PATTERNS, PROMISE_PATTERNS
from app.intelligence.llm import ImageInput, LLMGateway, Tier
from app.intelligence.pricing import PriceSuggestion

Strategy = Literal["quick", "market", "premium"]
STRATEGY_LABEL = {"quick": "低价挂牌", "market": "挂牌参考价", "premium": "高价试水"}

_BANNED = [re.compile(p, re.IGNORECASE) for p in (*OFF_PLATFORM_PATTERNS, *PROMISE_PATTERNS)]
# 不该出现在公开描述里的“元叙述”：不确定的信息应放进待确认清单，而不是写给买家看
_META = re.compile(r"未说明|未提供|未确认|以卖家确认为准|以实物为准|文案不展开|卖家未|无法确认|无法判断|暂不展开")
_SENTENCE = re.compile(r"[^。！？!?\n]+[。！？!?]?\n?")


class FaqItem(BaseModel):
    q: str
    a: str


class ListingAI(BaseModel):
    """大模型输出（结构化）。"""

    titles: list[str] = Field(description="3 个候选标题，每个不超过 30 字")
    desc: str = Field(description="150~300 字商品描述")
    brand_model: str = Field(description="品牌型号，看不出填空字符串")
    condition: str = Field(description="全新/99新/95新/9成新/8成新及以下")
    category_hint: str
    search_keyword: str = Field(description="搜索同款比价的关键词：只含品牌和型号（2~4 个词），不含成色、电池等描述")
    highlights: list[str]
    flaws: list[str] = Field(description="图片或说明中可见的瑕疵，没有则为空")
    accessories: list[str]
    is_virtual: bool = Field(description="是否虚拟商品（卡券、会员、教程、账号等）")
    shipping_mode: Literal["free", "by_distance", "fixed", "no_shipping"]
    post_fee: float = Field(description="shipping_mode=fixed 时的运费，否则为 0")
    shipping_reason: str
    price_guess: float | None = Field(
        description="二手合理成交价估计（元）。型号不确定时按最可能的型号估计并在 uncertain 中说明；只有完全无法判断品类时才为 null"
    )
    orig_price_guess: float | None = Field(description="全新时的官方 / 市场售价（元），不确定时为 null")
    user_price: float | None = Field(description="卖家说明中明确给出的售价，没有为 null")
    user_floor: float | None = Field(description="卖家说明中明确给出的最低价，没有为 null")
    faq: list[FaqItem] = Field(description="5~8 条买家常见问题及回答，只基于可确认的信息")
    cover_index: int = Field(description="最适合作封面的图片序号（从 0 开始）")
    uncertain: list[str] = Field(description="需要卖家确认的信息，例如图片看不清的型号、容量、是否有发票")


SYSTEM = """你是闲鱼资深卖家助手，根据卖家上传的商品图片和补充说明，生成一份可以直接发布的商品草稿。

要求：
1. 标题：3 个，各不超过 30 字，包含品牌型号与核心卖点，口吻像真实个人卖家，不用夸张营销词。
2. 描述：150~300 字，依次说明 入手渠道 / 时间（卖家说了才写）、成色与瑕疵（如实）、配件、出售原因、交易方式。
   不要出现任何站外联系方式，不要写“保证正品”“假一赔十”“包退包换”等承诺。
3. 只依据图片和卖家说明，看不清或无法确认的信息不要编造，写进 uncertain 让卖家确认。
   描述是公开给买家看的：不知道的信息直接不写，不要出现“未说明”“以卖家确认为准”“具体以实物为准”之类的话。
4. 价格：卖家说明里明确给了售价 / 最低价就填 user_price / user_floor；同时总要尽量给出 price_guess（二手行情估计），
   卖家会在确认页核对。
5. search_keyword 只写品牌 + 型号（例如“iPhone 13 128G”“Switch Lite”），不要带成色、电池、瑕疵等描述。
6. 运费：体积小、价值较高的商品通常包邮（free）；大件或很重的选按距离（by_distance）；虚拟商品选 no_shipping。
7. faq：站在买家角度提问（成色、配件、能否小刀、怎么发货等），回答只用可确认的信息，不确定的回答“以卖家确认为准”。"""


class ListingDraftOut(BaseModel):
    """生成结果：草稿字段 + 供确认页展示的 AI 信息。"""

    title: str
    desc: str
    image_ids: list[str]
    price: float | None
    orig_price: float | None
    floor_price: float | None
    shipping: str
    post_fee: float
    is_virtual: bool
    knowledge: str
    meta: dict[str, Any]


def clean_listing_text(text: str) -> tuple[str, list[str]]:
    """删除包含站外联系方式或承诺性表述的句子，返回 (清洗后文本, 被删除的句子)。"""
    kept: list[str] = []
    removed: list[str] = []
    for sentence in _SENTENCE.findall(text):
        if any(p.search(sentence) for p in _BANNED):
            removed.append(sentence.strip())
        else:
            kept.append(sentence)
    return "".join(kept).strip(), removed


def strip_meta_sentences(text: str) -> str:
    """去掉“未说明”“以卖家确认为准”之类写给卖家而不是买家的句子。"""
    return "".join(s for s in _SENTENCE.findall(text) if not _META.search(s)).strip()


def _round_price(value: float) -> float:
    return float(math.floor(value)) if value >= 100 else round(value, 1)


def decide_pricing(
    ai: ListingAI, suggestion: PriceSuggestion | None, strategy: Strategy
) -> tuple[float | None, float | None, float | None, str, list[str]]:
    """返回 (售价, 底价, 原价, 定价依据, 提醒)。优先级：卖家指定 > 同款行情 > AI 估价。"""
    warnings: list[str] = []
    if ai.user_price and ai.user_price > 0:
        price, source = ai.user_price, "卖家说明中给出的价格"
    elif suggestion is not None:
        price = {"quick": suggestion.quick_sale, "market": suggestion.market, "premium": suggestion.premium}[strategy]
        source = f"同类在售挂牌价参考（{suggestion.basis.count} 个样本，{STRATEGY_LABEL[strategy]}；非实际成交价）"
    elif ai.price_guess and ai.price_guess > 0:
        price, source = ai.price_guess, "AI 估价"
        warnings.append("同款在售样本不足，售价为 AI 估计，请重点确认")
    else:
        return None, None, None, "无法估价", ["无法估价，请手动填写售价"]

    price = _round_price(price)
    if ai.user_floor and 0 < ai.user_floor <= price:
        floor = ai.user_floor
    else:
        if ai.user_floor and ai.user_floor > price:
            warnings.append("说明中的最低价高于售价，已忽略")
        floor = price * 0.85
        if suggestion is not None:
            floor = max(floor, suggestion.quick_sale * 0.95)
        floor = min(_round_price(floor), price)
    orig = ai.orig_price_guess if ai.orig_price_guess and ai.orig_price_guess > price else None
    return price, floor, (_round_price(orig) if orig else None), source, warnings


def build_knowledge(ai: ListingAI) -> str:
    lines = ["## 商品信息"]
    if ai.brand_model:
        lines.append(f"- 品牌型号：{ai.brand_model}")
    lines.append(f"- 成色：{ai.condition}")
    if ai.accessories:
        lines.append(f"- 配件：{'、'.join(ai.accessories)}")
    lines.append(f"- 瑕疵：{'；'.join(ai.flaws) if ai.flaws else '暂无明显瑕疵'}")
    if ai.faq:
        lines.append("")
        lines.append("## 常见问题")
        for item in ai.faq:
            lines.append(f"Q：{item.q}")
            lines.append(f"A：{item.a}")
    return "\n".join(lines)


async def generate_listing(
    llm: LLMGateway,
    *,
    images: list[tuple[str, bytes, str]],
    hint: str,
    strategy: Strategy,
    market_lookup,  # async (keyword) -> MarketView | None  # noqa: ANN001
) -> ListingDraftOut:
    """images: [(image_id, bytes, media_type)]，前 N 张交给模型看（N 受模型配置限制）。"""
    shown = images[: llm.config.max_images]
    ai = await llm.complete_json(
        Tier.VISION,
        SYSTEM,
        f"卖家补充说明：{hint.strip() or '无'}\n共 {len(shown)} 张图片，序号从 0 开始。",
        ListingAI,
        images=[ImageInput(data=data, media_type=media) for _, data, media in shown],
        max_tokens=4000,
        effort="medium",
    )

    warnings: list[str] = []
    market = None
    if ai.search_keyword.strip():
        try:
            market = await market_lookup(ai.search_keyword.strip())
        except Exception as e:  # noqa: BLE001  行情只是参考，失败时改用 AI 估价并提示原因
            warnings.append(f"同款行情查询失败（{e}），售价改用 AI 估计")
    suggestion = market.suggestion if market is not None else None
    price, floor, orig, price_source, price_warnings = decide_pricing(ai, suggestion, strategy)
    warnings += price_warnings

    titles = [t.strip()[:60] for t in ai.titles if t.strip()] or [ai.brand_model or "闲置转让"]
    desc, removed = clean_listing_text(ai.desc)
    desc = strip_meta_sentences(desc) or desc
    titles_clean = []
    for t in titles:
        cleaned, t_removed = clean_listing_text(t)
        if cleaned:
            titles_clean.append(cleaned)
        removed += t_removed
    if removed:
        warnings.append(f"已自动删除 {len(removed)} 处站外联系方式或承诺性表述")

    image_ids = [image_id for image_id, _, _ in images]
    cover = ai.cover_index if 0 <= ai.cover_index < len(shown) else 0
    if cover:
        image_ids.insert(0, image_ids.pop(cover))

    shipping = "no_shipping" if ai.is_virtual else ai.shipping_mode
    return ListingDraftOut(
        title=(titles_clean or titles)[0],
        desc=desc or ai.desc,
        image_ids=image_ids,
        price=price,
        orig_price=orig,
        floor_price=floor,
        shipping=shipping,
        post_fee=ai.post_fee if shipping == "fixed" else 0,
        is_virtual=ai.is_virtual,
        knowledge=build_knowledge(ai),
        meta={
            "generated_at": datetime.now(UTC).isoformat(),
            "model": llm.model_for(Tier.VISION),
            "strategy": strategy,
            "titles": titles_clean or titles,
            "brand_model": ai.brand_model,
            "condition": ai.condition,
            "category_hint": ai.category_hint,
            "highlights": ai.highlights,
            "flaws": ai.flaws,
            "accessories": ai.accessories,
            "shipping_reason": ai.shipping_reason,
            "price_source": price_source,
            "price_guess": ai.price_guess,
            "search_keyword": ai.search_keyword,
            "market": market.model_dump() if market is not None else None,
            "uncertain": ai.uncertain,
            "warnings": warnings,
            "removed": removed,
            "cover_changed": bool(cover),
        },
    )
