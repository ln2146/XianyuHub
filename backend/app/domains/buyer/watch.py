"""单品价格监控：定时拉取单个商品详情 → 记录价格快照 → 到价提醒 / 售出下架自动停止。

与关键词「自动搜货」任务相互独立：这里只关心用户已经看中的某一件商品。
调度方式：一个全局的间隔任务每几分钟扫描一次「到期」的监控项（last_checked_at + interval ≤ now），
逐个查询详情，两次请求之间随机延时，单轮有数量上限，避免集中请求触发风控。
"""

import asyncio
import random
import re
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import or_, select

from app.core.db import session_factory
from app.domains.buyer.models import PriceWatch, WatchStatus
from app.domains.buyer.pipeline import upsert_market_item
from app.goofish.dto import ItemDetail
from app.goofish.errors import BizError, GoofishError, RiskBlockedError, RiskControlError
from app.notify.senders import Notification
from app.notify.service import NotifyEvents, notify
from app.runtime import get_runtime

MAX_PER_ROUND = 30
MAX_FAILURES_BEFORE_PAUSE = 5
_ENDED_WORDS = ("售出", "卖掉", "已售", "下架", "删除", "关闭", "失效", "不存在")
_round_lock = asyncio.Lock()


class WatchInputError(ValueError):
    pass


def parse_item_id(text: str) -> str:
    """支持纯数字 ID 或带 id= 参数的商品链接（goofish.com / 2.taobao.com 等）。"""
    s = (text or "").strip()
    if re.fullmatch(r"\d{6,20}", s):
        return s
    m = re.search(r"[?&](?:id|itemId|item_id)=(\d{6,20})", s)
    if m:
        return m.group(1)
    if "tb.cn" in s:
        raise WatchInputError("暂不支持短链接，请在浏览器打开后复制完整的商品链接，或直接填写商品 ID")
    raise WatchInputError("无法识别商品 ID，请粘贴商品链接（含 id= 参数）或纯数字 ID")


def ended_reason(detail: ItemDetail) -> str | None:
    status = (detail.status or "").strip()
    if any(w in status for w in _ENDED_WORDS):
        return f"商品状态：{status}"
    return None


def alert_hit(w: PriceWatch, price: float | None) -> str | None:
    """返回命中的提醒条件描述；未命中返回 None。"""
    if price is None:
        return None
    if w.target_price is not None and price <= w.target_price:
        return f"已降到目标价 ¥{w.target_price:g} 以下"
    if w.drop_percent and w.base_price and price <= w.base_price * (1 - w.drop_percent / 100):
        drop = (1 - price / w.base_price) * 100
        return f"较加入时 ¥{w.base_price:g} 降价 {drop:.0f}%"
    return None


def _aware(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def is_due(w: PriceWatch, now: datetime) -> bool:
    last = _aware(w.last_checked_at)
    return last is None or last + timedelta(minutes=w.interval_minutes) <= now


async def apply_detail(w: PriceWatch, detail: ItemDetail, s) -> str | None:  # noqa: ANN001
    """把一次详情结果写入监控项和市场商品库，返回需要发出的提醒类型（triggered / ended / None）。"""
    await upsert_market_item(s, detail.item)
    now = datetime.now(UTC)
    price = detail.item.price
    w.title = detail.item.title or w.title
    w.image_url = detail.item.image_url or w.image_url
    w.link = detail.item.link or w.link
    w.item_status = (detail.status or "")[:32]
    w.last_checked_at = now
    w.last_error = None
    w.consecutive_failures = 0
    if price is not None:
        w.last_price = price
        w.lowest_price = price if w.lowest_price is None else min(w.lowest_price, price)
        if w.base_price is None:
            w.base_price = price
    reason = ended_reason(detail)
    if reason:
        w.status, w.enabled, w.ended_reason = WatchStatus.ENDED, False, reason
        return "ended"
    if w.status == WatchStatus.WATCHING and alert_hit(w, price):
        # 到价提醒一次后自动暂停，避免价格来回波动时反复打扰；用户可重新开启
        w.status, w.enabled, w.triggered_at = WatchStatus.TRIGGERED, False, now
        return "triggered"
    return None


async def _send(owner_id: int, w: PriceWatch, kind: str, hit: str | None) -> None:
    if kind == "triggered":
        title = f"🎯 到价提醒：{w.title[:30]}"
        content = f"当前 ¥{w.last_price:g}，{hit}" + (f"\n备注：{w.note}" if w.note else "")
    else:
        title = f"⛔ 已停止监控：{w.title[:30]}"
        content = f"{w.ended_reason or '商品已下架'}，最后价格 ¥{(w.last_price or 0):g}"
    await notify(
        owner_id,
        Notification(
            event=NotifyEvents.PRICE_DROP, title=title, content=content, url=w.link, image_url=w.image_url or None
        ),
    )


async def check_watch(watch_id: int) -> PriceWatch | None:
    """检查单个监控项；风控异常向上抛出，由调用方决定是否中断本轮。"""
    async with session_factory()() as s:
        w = await s.get(PriceWatch, watch_id)
        if w is None:
            return None
        item_id, account_id = w.item_id, w.account_id
    try:
        detail = await get_runtime().gateway.get_item_detail(item_id, account_id=account_id)
    except BizError as e:
        # 商品不存在 / 已删除：业务失败，直接视为结束
        async with session_factory()() as s:
            w = await s.get(PriceWatch, watch_id)
            if w is None:
                return None
            w.status, w.enabled, w.ended_reason = WatchStatus.ENDED, False, f"商品不可访问：{str(e)[:80]}"
            w.last_checked_at = datetime.now(UTC)
            owner_id = w.owner_id
            await s.commit()
            await s.refresh(w)
        await _send(owner_id, w, "ended", None)
        return w
    except (RiskBlockedError, RiskControlError):
        raise
    except GoofishError as e:
        async with session_factory()() as s:
            w = await s.get(PriceWatch, watch_id)
            if w is None:
                return None
            w.last_checked_at = datetime.now(UTC)
            w.last_error = str(e)[:500]
            w.consecutive_failures += 1
            if w.consecutive_failures >= MAX_FAILURES_BEFORE_PAUSE:
                w.status, w.enabled = WatchStatus.PAUSED, False
            await s.commit()
            await s.refresh(w)
        return w

    async with session_factory()() as s:
        w = await s.get(PriceWatch, watch_id)
        if w is None:
            return None
        kind = await apply_detail(w, detail, s)
        hit = alert_hit(w, w.last_price) if kind == "triggered" else None
        owner_id = w.owner_id
        await s.commit()
        await s.refresh(w)
    if kind:
        await _send(owner_id, w, kind, hit)
    return w


async def check_due_watches() -> int:
    """调度入口：检查到期的监控项，返回本轮检查数量。"""
    if _round_lock.locked():
        return 0
    async with _round_lock:
        now = datetime.now(UTC)
        async with session_factory()() as s:
            rows = (
                await s.execute(
                    select(PriceWatch)
                    .where(PriceWatch.enabled.is_(True), PriceWatch.status == WatchStatus.WATCHING)
                    .where(or_(PriceWatch.last_checked_at.is_(None), PriceWatch.last_checked_at <= now))
                    .order_by(PriceWatch.last_checked_at.is_not(None), PriceWatch.last_checked_at)
                )
            ).scalars()
            due = [w.id for w in rows if is_due(w, now)][:MAX_PER_ROUND]
        checked = 0
        for i, watch_id in enumerate(due):
            if i:
                # 两次详情请求之间随机延时 1.8 ~ 3.2 秒，模拟真实浏览节奏
                await asyncio.sleep(random.uniform(1.8, 3.2))
            try:
                await check_watch(watch_id)
                checked += 1
            except (RiskBlockedError, RiskControlError) as e:
                logger.warning("单品价格监控触发风控，本轮提前结束：{}", e)
                break
            except Exception:  # noqa: BLE001
                logger.exception("单品价格监控 {} 检查异常", watch_id)
        return checked
