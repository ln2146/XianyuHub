"""选品雷达流水线：采集 → 去重 / 价格快照 → 规则初筛 → 价格情报 → 文本粗筛 → 详情 / 画像 → AI 判定 → 推送。"""

import asyncio
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
import random
from typing import Any

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory
from app.core.events import Topics, bus
from app.domains.buyer.ai import build_item_context, judge_item, prescreen_item
from app.domains.buyer.models import (
    MarketItemRecord,
    MonitorTask,
    PriceSnapshot,
    ResultStage,
    SellerProfileCache,
    TaskResult,
    Verdict,
)
from app.goofish.dto import MarketItem, SearchQuery
from app.goofish.errors import GoofishError, RiskBlockedError, RiskControlError
from app.intelligence.llm import LLMError, LLMUnavailable, Tier, get_llm
from app.intelligence.pricing import MarketStats, deal_label, deal_score, market_stats
from app.intelligence.rules import ItemRules, check_item
from app.notify.senders import Notification
from app.notify.service import NotifyEvents, notify
from app.runtime import get_runtime

PROFILE_TTL = timedelta(hours=24)
MAX_FAILURES_BEFORE_PAUSE = 3
_locks: dict[int, asyncio.Lock] = {}


@dataclass
class RunStats:
    fetched: int = 0
    new: int = 0
    filtered: int = 0
    prescreen_rejected: int = 0
    evaluated: int = 0
    recommended: int = 0
    price_drops: int = 0
    errors: int = 0
    notes: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {k: v for k, v in self.__dict__.items()}


def task_lock(task_id: int) -> asyncio.Lock:
    return _locks.setdefault(task_id, asyncio.Lock())


# ---------------------------------------------------------------- 存储
async def upsert_market_item(s: AsyncSession, item: MarketItem) -> tuple[MarketItemRecord, float | None]:
    """返回 (记录, 旧价格)。价格变化时追加快照。"""
    rec = await s.get(MarketItemRecord, item.item_id)
    now = datetime.now(UTC)
    old_price = None
    if rec is None:
        rec = MarketItemRecord(item_id=item.item_id, first_seen_at=now)
        s.add(rec)
    else:
        old_price = rec.price
    for attr in ("title", "area", "seller_nick", "link", "image_url"):
        value = getattr(item, attr)
        if value:
            setattr(rec, attr, value)
    for attr in ("price", "orig_price", "want_cnt", "browse_cnt", "seller_id", "publish_time"):
        value = getattr(item, attr)
        if value is not None:
            setattr(rec, attr, value)
    if item.images:
        rec.images = item.images
    if item.tags:
        rec.tags = item.tags
    if item.desc:
        rec.desc = item.desc
    rec.last_seen_at = now
    if item.price is not None and item.price != old_price:
        s.add(PriceSnapshot(item_id=item.item_id, price=item.price, seen_at=now))
    return rec, old_price


def record_to_dict(rec: MarketItemRecord) -> dict[str, Any]:
    return {
        "标题": rec.title,
        "价格": rec.price,
        "原价": rec.orig_price,
        "想要人数": rec.want_cnt,
        "浏览量": rec.browse_cnt,
        "发货地": rec.area,
        "发布时间": rec.publish_time.isoformat() if rec.publish_time else None,
        "标签": rec.tags,
        "描述": (rec.desc or "")[:1500],
        "卖家昵称": rec.seller_nick,
        "卖家芝麻信用": rec.seller_zhima,
        "卖家注册天数": rec.seller_reg_days,
    }


async def historical_stats(s: AsyncSession, task_id: int, current: list[float | None]) -> MarketStats:
    """价格情报：本次采集 + 该任务近 30 天见过的商品价格。"""
    since = datetime.now(UTC) - timedelta(days=30)
    rows = await s.execute(
        select(MarketItemRecord.price)
        .join(TaskResult, TaskResult.item_id == MarketItemRecord.item_id)
        .where(TaskResult.task_id == task_id, MarketItemRecord.last_seen_at >= since)
    )
    return market_stats([*current, *(r[0] for r in rows)])


# ---------------------------------------------------------------- 卖家画像
async def seller_profile(task: MonitorTask, seller_id: str) -> dict[str, Any] | None:
    async with session_factory()() as s:
        cached = await s.get(SellerProfileCache, seller_id)
        if cached is not None:
            fetched = cached.fetched_at if cached.fetched_at.tzinfo else cached.fetched_at.replace(tzinfo=UTC)
            if datetime.now(UTC) - fetched < PROFILE_TTL:
                return cached.data
    profile = await get_runtime().gateway.get_seller_profile(seller_id, task.account_id)
    rate = profile.seller_positive_rate
    data = {
        "昵称": profile.nick,
        "简介": profile.introduction,
        "卖家信用": profile.seller_credit,
        "买家信用": profile.buyer_credit,
        "商品数": profile.item_cnt,
        "评价数": profile.rate_cnt,
        "作为卖家的好评率": f"{rate:.0%}" if rate is not None else "未知",
        "在售/已售商品（节选）": [f"{i['title']} ¥{i['price']} {i['status']}" for i in profile.items[:20]],
        "最近评价（节选）": [f"[{r.role}] {r.content}" for r in profile.ratings[:15] if r.content],
    }
    async with session_factory()() as s:
        row = await s.get(SellerProfileCache, seller_id)
        if row is None:
            s.add(SellerProfileCache(seller_id=seller_id, data=data))
        else:
            row.data, row.fetched_at = data, datetime.now(UTC)
        await s.commit()
    return data


# ---------------------------------------------------------------- 主流程
async def run_task(task_id: int) -> RunStats:
    lock = task_lock(task_id)
    if lock.locked():
        logger.info("任务 {} 正在运行，跳过本次触发", task_id)
        return RunStats(notes=["已在运行"])
    async with lock:
        from app.core.cluster import get_cluster

        cluster = get_cluster()
        token = await cluster.try_lock(f"buyer.task.{task_id}", 1800) if cluster else None
        if cluster and token is None:
            logger.info("任务 {} 正在其他进程运行，跳过本次触发", task_id)
            return RunStats(notes=["已在其他进程运行"])
        try:
            return await _run(task_id)
        finally:
            if cluster and token:
                await cluster.unlock(f"buyer.task.{task_id}", token)


async def _run(task_id: int) -> RunStats:
    stats = RunStats()
    async with session_factory()() as s:
        task = await s.get(MonitorTask, task_id)
        if task is None or not task.enabled:
            return stats
        if task.paused_reason:
            stats.notes.append("任务已暂停")
            return stats
        owner_id = task.owner_id
    try:
        await _collect_and_evaluate(task, stats)
        status, error = "ok", None
    except (RiskBlockedError, RiskControlError) as e:
        status, error = "risk", str(e)
    except GoofishError as e:
        status, error = "error", str(e)
    except Exception as e:  # noqa: BLE001
        logger.exception("选品任务 {} 异常", task_id)
        status, error = "error", repr(e)

    async with session_factory()() as s:
        task = await s.get(MonitorTask, task_id)
        if task is None:
            return stats
        task.last_run_at = datetime.now(UTC)
        task.last_status = status
        task.last_error = error
        task.last_stats = stats.as_dict()
        if status == "ok":
            task.consecutive_failures = 0
        else:
            task.consecutive_failures += 1
            if task.consecutive_failures >= MAX_FAILURES_BEFORE_PAUSE or status == "risk":
                task.paused_reason = f"连续失败 {task.consecutive_failures} 次：{error}"
        paused = task.paused_reason
        name = task.name
        await s.commit()
    if status != "ok" and paused:
        await notify(
            owner_id,
            Notification(event=NotifyEvents.TASK_FAILED, title=f"选品任务「{name}」已暂停", content=paused or ""),
        )
    return stats


async def _collect_and_evaluate(task: MonitorTask, stats: RunStats) -> None:
    gateway = get_runtime().gateway
    rules = ItemRules.model_validate(task.rules or {})
    if rules.min_price is None:
        rules.min_price = task.min_price
    if rules.max_price is None:
        rules.max_price = task.max_price

    seen: dict[str, MarketItem] = {}
    first_search = True
    for keyword in task.keywords:
        for page in range(1, max(1, task.max_pages) + 1):
            if not first_search:
                # 降低搜索速度：两次请求之间随机延时 2.5 ~ 4.2 秒，模拟真实浏览节奏，降低被平台限流的概率
                await asyncio.sleep(random.uniform(2.5, 4.2))
            first_search = False

            q = SearchQuery(
                keyword=keyword,
                page=page,
                sort=task.sort,
                min_price=int(task.min_price) if task.min_price is not None else None,
                max_price=int(task.max_price) if task.max_price is not None else None,
                province=task.province,
                city=task.city,
                publish_days=task.publish_days,
                personal_only=task.personal_only,
                free_shipping=task.free_shipping,
            )
            result = await gateway.search_items(q, task.account_id)
            for item in result.items:
                seen.setdefault(item.item_id, item)
            if not result.has_more:
                break
    stats.fetched = len(seen)

    candidates: list[str] = []
    async with session_factory()() as s:
        price_stats = await historical_stats(s, task.id, [i.price for i in seen.values()])
        existing = {
            r.item_id: r
            for r in (
                await s.execute(
                    select(TaskResult).where(TaskResult.task_id == task.id, TaskResult.item_id.in_(list(seen)))
                )
            ).scalars()
        }
        for item in seen.values():
            rec, old_price = await upsert_market_item(s, item)
            res = existing.get(item.item_id)
            if res is not None:
                await _check_price_drop(task, res, rec, old_price, stats)
                continue
            stats.new += 1
            score = deal_score(item.price, price_stats)
            reasons = check_item(item, rules)
            res = TaskResult(task_id=task.id, item_id=item.item_id, deal_score=score, price_at_eval=item.price)
            s.add(res)
            if reasons:
                res.stage, res.filter_reasons = ResultStage.FILTERED, reasons
                stats.filtered += 1
                continue
            if task.decision_mode == "rule":
                res.stage, res.verdict = ResultStage.EVALUATED, Verdict.RECOMMEND
                res.reason = f"满足全部规则；{deal_label(score)}"
                stats.recommended += 1
                continue
            candidates.append(item.item_id)
        await s.commit()

    # 规则模式：直接推送
    if task.decision_mode == "rule":
        await _notify_new_recommendations(task)
        return

    llm = get_llm()
    first_cand = True
    for item_id in candidates:
        if not first_cand:
            # 候选商品详情拉取间隔：1.8 ~ 3.2 秒，防止频繁调用 detail 接口触发风控
            await asyncio.sleep(random.uniform(1.8, 3.2))
        first_cand = False

        try:
            await _evaluate_candidate(task, item_id, rules, price_stats, llm, stats)
        except (RiskBlockedError, RiskControlError):
            raise
        except (GoofishError, LLMError) as e:
            stats.errors += 1
            async with session_factory()() as s:
                res = await _result(s, task.id, item_id)
                res.stage, res.reason = ResultStage.ERROR, str(e)[:500]
                await s.commit()
        except LLMUnavailable as e:
            stats.notes.append(f"大模型不可用，已改用规则判定：{e}")
            async with session_factory()() as s:
                res = await _result(s, task.id, item_id)
                res.stage, res.verdict = ResultStage.EVALUATED, Verdict.CONDITIONAL
                res.reason = "大模型不可用，仅通过规则初筛，请人工确认"
                await s.commit()
    await _notify_new_recommendations(task)


async def _result(s: AsyncSession, task_id: int, item_id: str) -> TaskResult:
    return (
        await s.execute(select(TaskResult).where(TaskResult.task_id == task_id, TaskResult.item_id == item_id))
    ).scalar_one()


async def _evaluate_candidate(task, item_id, rules, price_stats, llm, stats: RunStats) -> None:  # noqa: ANN001
    gateway = get_runtime().gateway
    async with session_factory()() as s:
        rec = await s.get(MarketItemRecord, item_id)
        assert rec is not None
        title, price = rec.title, rec.price

    if task.ai_prescreen and llm.available:
        pre = await prescreen_item(llm, criteria=task.criteria, title=title, price=price)
        if not pre.keep:
            async with session_factory()() as s:
                res = await _result(s, task.id, item_id)
                res.stage, res.verdict, res.reason = ResultStage.PRESCREEN_REJECTED, Verdict.REJECT, pre.reason
                await s.commit()
            stats.prescreen_rejected += 1
            return

    detail = await gateway.get_item_detail(item_id, task.account_id)
    async with session_factory()() as s:
        rec, _ = await upsert_market_item(s, detail.item)
        rec.seller_zhima = detail.seller.zhima_level or rec.seller_zhima
        rec.seller_reg_days = detail.seller.reg_days if detail.seller.reg_days is not None else rec.seller_reg_days
        rec.detail_fetched_at = datetime.now(UTC)
        await s.commit()
        reasons = check_item(detail.item, rules, zhima=rec.seller_zhima, reg_days=rec.seller_reg_days)
        item_dict = record_to_dict(rec)
        images = list(rec.images or ([rec.image_url] if rec.image_url else []))
        price = rec.price
        seller_id = rec.seller_id
        if reasons:
            res = await _result(s, task.id, item_id)
            res.stage, res.filter_reasons = ResultStage.FILTERED, reasons
            await s.commit()
            stats.filtered += 1
            return

    seller = None
    if task.fetch_seller_profile and seller_id:
        seller = await seller_profile(task, seller_id)

    score = deal_score(price, price_stats)
    context = build_item_context(item_dict, stats=price_stats, deal=score, seller=seller)
    out = await judge_item(llm, criteria=task.criteria, context=context, images=images if task.analyze_images else [])
    async with session_factory()() as s:
        res = await _result(s, task.id, item_id)
        res.stage = ResultStage.EVALUATED
        res.verdict = out.verdict
        res.confidence = out.confidence
        res.reason = out.reason
        res.risk_tags = out.risk_tags
        res.need_confirm = out.need_confirm
        res.questions = out.questions_for_seller
        res.seller_type = out.seller_type
        res.deal_score = score
        res.price_at_eval = price
        res.ai_model = llm.model_for(Tier.VISION)
        await s.commit()
    stats.evaluated += 1
    if out.verdict == Verdict.RECOMMEND:
        stats.recommended += 1


async def _check_price_drop(task, res: TaskResult, rec: MarketItemRecord, old_price, stats: RunStats) -> None:  # noqa: ANN001
    if (
        old_price
        and rec.price
        and rec.price < old_price * (1 - task.price_drop_percent / 100)
        and res.verdict in (Verdict.RECOMMEND, Verdict.CONDITIONAL)
        and res.mark != "ignored"
    ):
        stats.price_drops += 1
        await notify(
            task.owner_id,
            Notification(
                event=NotifyEvents.PRICE_DROP,
                title=f"📉 降价：{rec.title[:30]}",
                content=f"¥{old_price:g} → ¥{rec.price:g}（任务：{task.name}）",
                url=rec.link,
                image_url=rec.image_url or None,
            ),
        )


async def _notify_new_recommendations(task: MonitorTask) -> None:
    verdicts = [Verdict.RECOMMEND] + ([Verdict.CONDITIONAL] if task.notify_conditional else [])
    async with session_factory()() as s:
        rows = (
            await s.execute(
                select(TaskResult, MarketItemRecord)
                .join(MarketItemRecord, MarketItemRecord.item_id == TaskResult.item_id)
                .where(TaskResult.task_id == task.id, TaskResult.notified.is_(False), TaskResult.verdict.in_(verdicts))
            )
        ).all()
        for res, _rec in rows:
            res.notified = True
        await s.commit()
    for res, rec in rows:
        tag = "✅ 推荐" if res.verdict == Verdict.RECOMMEND else "🟡 有条件推荐"
        lines = [f"¥{rec.price:g}　{rec.area}　{deal_label(res.deal_score)}", res.reason]
        if res.need_confirm:
            lines.append("需确认：" + "、".join(res.need_confirm))
        await notify(
            task.owner_id,
            Notification(
                event=NotifyEvents.ITEM_RECOMMENDED,
                title=f"{tag}｜{rec.title[:40]}",
                content="\n".join(line for line in lines if line),
                url=rec.link,
                image_url=rec.image_url or None,
            ),
        )
        await bus.publish(Topics.MARKET_ITEM_RECOMMENDED, {"task_id": task.id, "item_id": rec.item_id})
