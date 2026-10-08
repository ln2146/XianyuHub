import json

import httpx
from loguru import logger
from sqlalchemy import select

from app.core.crypto import get_vault
from app.core.db import session_factory
from app.notify.models import NotificationChannel
from app.notify.senders import SENDERS, Notification


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


async def notify(owner_id: int | None, n: Notification) -> int:
    """向 owner 订阅了该事件的所有渠道发送，返回成功数。owner_id 为空时发给所有用户的渠道。"""
    async with session_factory()() as session:
        stmt = select(NotificationChannel).where(NotificationChannel.enabled.is_(True))
        if owner_id is not None:
            stmt = stmt.where(NotificationChannel.owner_id == owner_id)
        channels = [c for c in (await session.execute(stmt)).scalars() if c.wants(n.event)]
        ok = 0
        async with httpx.AsyncClient(timeout=15) as http:
            for ch in channels:
                try:
                    await send_to_channel(ch, n, http)
                    ch.last_error = None
                    ok += 1
                except Exception as e:  # noqa: BLE001
                    ch.last_error = str(e)[:500]
                    logger.warning("通知发送失败 channel={} type={} err={}", ch.name, ch.type, e)
        await session.commit()
        return ok
