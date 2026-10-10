import asyncio
import json
import time
from collections.abc import Coroutine
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select

from app.core.crypto import get_vault
from app.core.db import session_factory
from app.domains.system.models import Role, User
from app.notify.models import NotificationChannel
from app.notify.senders import SENDERS, Notification, SendError

# 临时故障（网络抖动 / 服务端 5xx / 429）重试一次
RETRY_DELAY_SECONDS = 2.0
# 同一 dedupe_key 在冷却时间内只发一次，避免同类告警刷屏
_recent: dict[str, float] = {}
_tasks: set[asyncio.Task] = set()


class NotifyEvents:
    """可订阅的通知事件。"""

    ITEM_RECOMMENDED = "item_recommended"
    PRICE_DROP = "price_drop"
    ACCOUNT_RISK = "account_risk"
    ACCOUNT_LOGIN_REQUIRED = "account_login_required"
    NEW_MESSAGE = "new_message"
    HUMAN_HANDOFF = "human_handoff"
    ORDER_PAID = "order_paid"
    DELIVERY_FAILED = "delivery_failed"
    STOCK_LOW = "stock_low"
    TASK_FAILED = "task_failed"
    ITEM_RELISTED = "item_relisted"

    ALL = [
        ITEM_RECOMMENDED,
        PRICE_DROP,
        ACCOUNT_RISK,
        ACCOUNT_LOGIN_REQUIRED,
        NEW_MESSAGE,
        HUMAN_HANDOFF,
        ORDER_PAID,
        DELIVERY_FAILED,
        STOCK_LOW,
        TASK_FAILED,
        ITEM_RELISTED,
    ]


def decode_config(channel: NotificationChannel) -> dict:
    return json.loads(get_vault().decrypt(channel.config_enc) or "{}")


def encode_config(cfg: dict) -> str:
    return get_vault().encrypt(json.dumps(cfg, ensure_ascii=False)) or ""


async def send_to_channel(channel: NotificationChannel, n: Notification, http: httpx.AsyncClient | None = None) -> None:
    sender, _ = SENDERS[channel.type]
    own = http is None
    http = http or httpx.AsyncClient(timeout=15)
    try:
        await sender(http, decode_config(channel), n)
    finally:
        if own:
            await http.aclose()


def _retryable(e: Exception) -> bool:
    if isinstance(e, SendError):
        return e.retryable
    return isinstance(e, httpx.TransportError)


async def _send_with_retry(ch: NotificationChannel, n: Notification, http: httpx.AsyncClient) -> None:
    try:
        await send_to_channel(ch, n, http)
    except Exception as e:  # noqa: BLE001
        if not _retryable(e):
            raise
        await asyncio.sleep(RETRY_DELAY_SECONDS)
        await send_to_channel(ch, n, http)


def _claim(dedupe_key: str | None, cooldown: float) -> bool:
    """冷却期内已发过同一 key 则返回 False。"""
    if not dedupe_key:
        return True
    now = time.monotonic()
    last = _recent.get(dedupe_key)
    if last is not None and now - last < cooldown:
        return False
    _recent[dedupe_key] = now
    if len(_recent) > 2000:  # 顺手清理过期记录，防止无限增长
        for k, ts in list(_recent.items()):
            if now - ts >= cooldown:
                _recent.pop(k, None)
    return True


def reset_dedupe() -> None:
    _recent.clear()


async def notify(
    owner_id: int | None,
    n: Notification,
    *,
    dedupe_key: str | None = None,
    cooldown: float = 600,
) -> int:
    """向 owner 订阅了该事件的所有渠道发送，返回成功数。

    owner_id 为空（事件不属于任何用户，如匿名搜索通道触发风控）时只发给管理员的渠道。
    传入 dedupe_key 时，同一 key 在 cooldown 秒内只发送一次。
    """
    if not _claim(dedupe_key, cooldown):
        return 0
    async with session_factory()() as session:
        stmt = select(NotificationChannel).where(NotificationChannel.enabled.is_(True))
        if owner_id is not None:
            stmt = stmt.where(NotificationChannel.owner_id == owner_id)
        else:
            admins = select(User.id).where(User.role == Role.ADMIN, User.is_active.is_(True))
            stmt = stmt.where(NotificationChannel.owner_id.in_(admins))
        channels = [c for c in (await session.execute(stmt)).scalars() if c.wants(n.event)]
        ok = 0
        async with httpx.AsyncClient(timeout=15) as http:
            for ch in channels:
                try:
                    await _send_with_retry(ch, n, http)
                    ch.last_error = None
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    ch.last_error = str(e)[:500]
                    logger.warning("通知发送失败 channel={} type={} err={}", ch.name, ch.type, e)
        await session.commit()
        return ok


async def _safe(coro: Coroutine[Any, Any, int]) -> None:
    try:
        await coro
    except Exception:  # noqa: BLE001
        logger.exception("后台通知异常")


def notify_background(
    owner_id: int | None,
    n: Notification,
    *,
    dedupe_key: str | None = None,
    cooldown: float = 600,
) -> asyncio.Task:
    """后台发送通知：用在订单发货等关键路径上，慢渠道（邮件 / 超时）不会拖慢业务。"""
    task = asyncio.create_task(_safe(notify(owner_id, n, dedupe_key=dedupe_key, cooldown=cooldown)))
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def drain() -> None:
    """等待所有后台通知发完（测试 / 优雅退出）。"""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
