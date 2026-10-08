"""买家侧 AI：商品判定、文本粗筛、自然语言建任务。

判定标准分三层：基础模板（输出格式与通用风险）+ 任务 criteria（品类标准 / 一票否决项）+ 价格情报。
"""

import json
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.intelligence.llm import ImageInput, LLMGateway, Tier
from app.intelligence.pricing import MarketStats, deal_label

JUDGE_SYSTEM = """你是一名经验丰富的闲鱼二手交易鉴定专家，替买家判断商品是否值得购买。

判定原则：
1. 一票否决：判定标准中标注为“必须”的条件不满足，直接 reject。
2. 图片优先：图片与文字描述冲突时，以图片为准，并在 risk_tags 中注明。
3. 卖家画像：结合卖家在售商品、评价和账号信息判断是个人玩家还是贩子 / 商家；
   大量同质商品、频繁上新、话术模板化通常意味着贩子。
4. 信息缺失：关键信息（如电池健康、维修史）缺失时不要直接否决，给出 conditional，
   并把需要向卖家确认的点写进 need_confirm，同时给出可直接发送的提问话术 questions_for_seller。
5. 价格异常：远低于市场价要警惕骗局、描述不符、监管机等风险。
6. 引导站外交易（加微信、私下转账）一律 reject。

只基于提供的信息判断，不要编造。reason 用 2~4 句中文说明关键依据。"""


class JudgeOut(BaseModel):
    verdict: Literal["recommend", "conditional", "reject"]
    confidence: float = Field(ge=0, le=1)
    reason: str
    risk_tags: list[str]
    need_confirm: list[str]
    questions_for_seller: list[str]
    seller_type: Literal["personal", "dealer", "unknown"]


class PrescreenOut(BaseModel):
    keep: bool
    reason: str


class TaskDraft(BaseModel):
    name: str
    keywords: list[str]
    min_price: float | None
    max_price: float | None
    province: str | None
    city: str | None
    publish_days: int | None
    personal_only: bool
    include_all: list[str]
    exclude: list[str]
    criteria: str


def build_item_context(
    item: dict[str, Any],
    *,
    stats: MarketStats | None,
    deal: int | None,
    seller: dict[str, Any] | None,
) -> str:
    parts = ["## 商品信息", json.dumps(item, ensure_ascii=False, default=str)]
    if stats and stats.count:
        parts += [
            "## 价格情报",
            f"同类在售样本 {stats.count} 个，P25={stats.p25}，中位数={stats.median}，P75={stats.p75}；"
            f"本商品性价比评分={deal}（{deal_label(deal)}）。",
        ]
    if seller:
        parts += ["## 卖家画像", json.dumps(seller, ensure_ascii=False, default=str)[:4000]]
    return "\n".join(parts)


async def judge_item(
    llm: LLMGateway,
    *,
    criteria: str,
    context: str,
    images: list[str],
) -> JudgeOut:
    user = f"# 判定标准\n{criteria or '（未提供具体标准，按通用二手交易常识判断）'}\n\n{context}"
    return await llm.complete_json(
        Tier.VISION,
        JUDGE_SYSTEM,
        user,
        JudgeOut,
        images=[ImageInput(url=u) for u in images if u],
        max_tokens=3000,
        effort="medium",
    )


async def prescreen_item(llm: LLMGateway, *, criteria: str, title: str, price: float | None) -> PrescreenOut:
    system = (
        "你在帮买家快速初筛闲鱼商品。只根据标题和价格判断是否明显不符合需求（型号不对、配件而非整机、求购帖、明显不相关）。"
        "拿不准时 keep=true。"
    )
    user = f"需求标准：\n{criteria[:1500]}\n\n商品标题：{title}\n价格：{price}"
    return await llm.complete_json(Tier.FAST, system, user, PrescreenOut, max_tokens=300, effort="low")


async def draft_task(llm: LLMGateway, description: str) -> TaskDraft:
    system = (
        "你帮用户把闲鱼蹲货需求转换成监控任务配置。\n"
        "- keywords：2~4 个搜索关键词（含常见别称 / 暗语，如“mba”“丐版”）\n"
        "- include_all：标题必须包含的词（谨慎，只放型号等硬条件）；exclude：排除词（如 配件、求购、坏、维修）\n"
        "- criteria：用 Markdown 写判定标准，包含“必须满足（一票否决）”“加分项”“危险信号”三部分\n"
        "- 用户没提到的条件填 null 或 false"
    )
    return await llm.complete_json(Tier.CHAT, system, description[:2000], TaskDraft, max_tokens=3000, effort="medium")
