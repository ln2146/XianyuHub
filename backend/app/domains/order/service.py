"""订单与自动发货。

付款事件 → 订单详情二次校验 → 发货前风控 → 分配卡券（原子出库）→ 按模式发消息 / 确认发货
→ 成功落库；失败释放卡密并指数退避重试，超过次数转人工并告警。
"""

import asyncio
import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
from loguru import logger
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import get_vault
from app.core.db import session_factory
from app.core.events import Topics, bus
from app.core.realtime import hub
from app.domains.account.models import XyAccount
from app.domains.message import service as message_service
from app.domains.message.models import MessageSource
from app.domains.order.models import (
    TRANSITIONS,
    BuyerBlacklist,
    CardBinding,
    CardItem,
    CardPool,
    DeliveryRecord,
    Order,
    OrderState,
)
from app.domains.system.audit import record_audit
from app.goofish.dto import SystemNotice
from app.goofish.errors import GoofishError
from app.goofish.parsers.trade import OrderStatus, RemoteOrder
from app.notify.senders import Notification
from app.notify.service import NotifyEvents, notify
from app.runtime import get_runtime

RETRY_DELAYS = [60, 120, 300, 600]  # 秒
DEFAULT_TEMPLATE = "您好，订单已发货，内容如下：\n{content}\n如有问题请随时联系～"
_order_locks: dict[int, asyncio.Lock] = {}
_push_tasks: set[asyncio.Task] = set()


class DeliveryError(Exception):
    pass


def fingerprint(content: str) -> str:
    return hashlib.sha256(content.strip().encode("utf-8")).hexdigest()


def _aware(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=UTC) if dt is not None and dt.tzinfo is None else dt


# ---------------------------------------------------------------- 状态机
async def transition(s: AsyncSession, order: Order, to: str, *, reason: str | None = None) -> bool:
    if order.status == to:
        return True
    if to not in TRANSITIONS.get(order.status, set()):
        logger.debug("忽略非法状态迁移 order={} {}->{}", order.order_id, order.status, to)
        return False
    result = await s.execute(update(Order).where(Order.id == order.id, Order.status == order.status).values(status=to))
    if result.rowcount != 1:
        return False  # 并发下已被其他流程改变
    order.status = to
    if reason is not None:
        order.fail_reason = reason
    _spawn_push({"id": order.id, "order_id": order.order_id, "status": to}, order.account_id)
    return True


def _spawn_push(data: dict[str, Any], account_id: int) -> None:
    """订单状态变化推送到前端（不阻塞事务）。"""
    task = asyncio.get_running_loop().create_task(hub.publish("order", data, account_id=account_id))
    _push_tasks.add(task)
    task.add_done_callback(_push_tasks.discard)


def _apply_remote(order: Order, remote: RemoteOrder) -> None:
    order.item_id = remote.item_id or order.item_id
    order.item_title = remote.item_title or order.item_title
    order.buyer_id = remote.buyer_id or order.buyer_id
    order.buyer_nick = remote.buyer_nick or order.buyer_nick
    order.amount = remote.amount if remote.amount is not None else order.amount
    order.quantity = remote.quantity or order.quantity
    order.spec_name = remote.spec_name or order.spec_name
    order.spec_value = remote.spec_value or order.spec_value
    order.is_bargain = remote.is_bargain or order.is_bargain
    order.remote_status = remote.status_text or remote.status


_REMOTE_TO_LOCAL = {
    OrderStatus.PENDING_PAY: OrderState.PENDING_PAY,
    OrderStatus.PAID: OrderState.PAID,
    OrderStatus.SHIPPED: OrderState.DELIVERED,
    OrderStatus.COMPLETED: OrderState.COMPLETED,
    OrderStatus.CLOSED: OrderState.CLOSED,
    OrderStatus.REFUNDING: OrderState.REFUNDING,
    OrderStatus.REFUNDED: OrderState.REFUNDED,
}


async def upsert_order(s: AsyncSession, account_id: int, order_id: str, **fields: Any) -> tuple[Order, bool]:
    order = (
        await s.execute(select(Order).where(Order.account_id == account_id, Order.order_id == order_id))
    ).scalar_one_or_none()
    created = order is None
    if order is None:
        order = Order(account_id=account_id, order_id=order_id, status=OrderState.PENDING_PAY)
        s.add(order)
        await s.flush()
    for k, v in fields.items():
        if v not in (None, ""):
            setattr(order, k, v)
    return order, created


# ---------------------------------------------------------------- 事件入口
async def on_order_event(payload: dict[str, Any]) -> None:
    account_id = payload.get("account_id")
    order_id = payload.get("order_id")
    notice = payload.get("notice")
    if account_id is None or not order_id:
        if notice == SystemNotice.PAID and account_id is not None:
            # 拿不到订单号时，主动同步一次待发货订单兜底
            await sync_orders(account_id)
        return
    async with session_factory()() as s:
        order, _ = await upsert_order(
            s,
            account_id,
            order_id,
            buyer_id=payload.get("buyer_id"),
            item_id=payload.get("item_id"),
            cid=payload.get("cid"),
        )
        if notice == SystemNotice.REFUND:
            await transition(s, order, OrderState.REFUNDING)
        elif notice == SystemNotice.CLOSED:
            await transition(s, order, OrderState.CLOSED)
        elif notice == SystemNotice.RECEIVED:
            await transition(s, order, OrderState.COMPLETED)
        elif notice == SystemNotice.SHIPPED and order.status in (OrderState.PAID, OrderState.RISK_HOLD):
            await transition(s, order, OrderState.DELIVERED)
        await s.commit()
        order_pk, status = order.id, order.status
    if notice == SystemNotice.PAID:
        await handle_paid(order_pk)
    elif notice == SystemNotice.REFUND:
        await _notify_owner(
            account_id,
            NotifyEvents.DELIVERY_FAILED,
            f"⚠️ 订单 {order_id} 买家申请退款",
            "已冻结该订单的自动发货，请人工处理。",
        )
    elif notice == SystemNotice.RECEIVED and status == OrderState.COMPLETED:
        await maybe_rate(order_pk)


async def handle_paid(order_pk: int) -> None:
    """付款：用订单详情接口二次校验（防止伪造的聊天文案触发发货），然后按设置自动发货。"""
    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        if order is None:
            return
        account_id, order_id = order.account_id, order.order_id
    try:
        remote = await get_runtime().gateway.get_order_detail(account_id, order_id)
    except GoofishError as e:
        logger.warning("订单详情获取失败 order={} err={}", order_id, e)
        remote = None
    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        if remote is not None:
            _apply_remote(order, remote)
            if remote.status not in (OrderStatus.PAID, OrderStatus.UNKNOWN):
                local = _REMOTE_TO_LOCAL.get(remote.status)
                if local:
                    await transition(s, order, local)
                await s.commit()
                return
        if order.status == OrderState.PENDING_PAY:
            await transition(s, order, OrderState.PAID)
        if order.paid_at is None:
            order.paid_at = datetime.now(UTC)
        await s.commit()
        acc = await s.get(XyAccount, account_id)
        settings = acc.get_settings()
        title, amount = order.item_title or order.item_id, order.amount
    await bus.publish(Topics.ORDER_PAID, {"account_id": account_id, "order_pk": order_pk})
    await _notify_owner(
        account_id, NotifyEvents.ORDER_PAID, f"💰 新订单已付款：{title}", f"金额：{amount}　订单号：{order_id}"
    )
    if settings.auto_delivery:
        await deliver(order_pk)


# ---------------------------------------------------------------- 发货
async def find_binding(s: AsyncSession, order: Order, owner_id: int) -> CardBinding | None:
    rows = (
        await s.execute(
            select(CardBinding).where(CardBinding.owner_id == owner_id, CardBinding.item_id == order.item_id)
        )
    ).scalars()
    best: tuple[int, CardBinding] | None = None
    for b in rows:
        if b.account_id not in (None, order.account_id):
            continue
        if b.spec_value and b.spec_value != order.spec_value:
            continue
        score = (2 if b.spec_value else 0) + (1 if b.account_id else 0)
        if best is None or score > best[0]:
            best = (score, b)
    return best[1] if best else None


async def precheck(s: AsyncSession, order: Order, owner_id: int, binding: CardBinding) -> str | None:
    """发货前风控，返回拦截原因。"""
    if order.buyer_id:
        hit = (
            await s.execute(
                select(BuyerBlacklist).where(
                    BuyerBlacklist.owner_id == owner_id, BuyerBlacklist.buyer_id == order.buyer_id
                )
            )
        ).scalar_one_or_none()
        if hit:
            return f"买家在黑名单：{hit.reason}"
        if binding.max_per_buyer:
            since = datetime.now(UTC) - timedelta(hours=24)
            n = (
                await s.execute(
                    select(func.count())
                    .select_from(Order)
                    .join(XyAccount, XyAccount.id == Order.account_id)
                    .where(
                        XyAccount.owner_id == owner_id,
                        Order.buyer_id == order.buyer_id,
                        Order.item_id == order.item_id,
                        Order.status.in_([OrderState.DELIVERED, OrderState.COMPLETED]),
                        Order.delivered_at >= since,
                    )
                )
            ).scalar_one()
            if n >= binding.max_per_buyer:
                return f"同一买家 24 小时内已发货 {n} 次（跨账号统计）"
    return None


async def allocate(s: AsyncSession, pool: CardPool, order: Order) -> tuple[str, int | None]:
    """返回 (内容, card_item_id)。卡密库存通过条件更新原子出库。"""
    if not pool.enabled:
        raise DeliveryError("卡券已停用")
    if pool.kind == "text":
        return get_vault().decrypt(pool.text_enc) or "", None
    if pool.kind == "pool":
        for _ in range(5):
            card = (
                await s.execute(
                    select(CardItem)
                    .where(CardItem.pool_id == pool.id, CardItem.status == "available")
                    .order_by(CardItem.id)
                    .limit(1)
                )
            ).scalar_one_or_none()
            if card is None:
                raise DeliveryError("卡密库存不足")
            res = await s.execute(
                update(CardItem)
                .where(CardItem.id == card.id, CardItem.status == "available")
                .values(status="locked", order_pk=order.id)
            )
            if res.rowcount == 1:
                return get_vault().decrypt(card.content_enc) or "", card.id
        raise DeliveryError("卡密分配冲突，请重试")
    if pool.kind == "api":
        return await call_delivery_api(pool.api_config, order), None
    raise DeliveryError(f"未知卡券类型 {pool.kind}")


def _render(template: str, order: Order, content: str = "") -> str:
    values = {
        "content": content,
        "order_id": order.order_id,
        "buyer_id": order.buyer_id or "",
        "buyer_name": order.buyer_nick or "",
        "item_id": order.item_id or "",
        "item_title": order.item_title or "",
        "spec": order.spec_value or "",
        "quantity": str(order.quantity),
    }
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


async def call_delivery_api(cfg: dict[str, Any], order: Order) -> str:
    url = cfg.get("url", "")
    if not url.startswith(("http://", "https://")):
        raise DeliveryError("API 取货地址无效")
    method = cfg.get("method", "POST").upper()
    body = json.loads(_render(json.dumps(cfg.get("body") or {}, ensure_ascii=False), order) or "{}")
    async with httpx.AsyncClient(timeout=float(cfg.get("timeout", 15))) as http:
        resp = await http.request(
            method,
            url,
            headers=cfg.get("headers") or {},
            json=body if method != "GET" else None,
            params=body if method == "GET" else None,
        )
    if resp.status_code >= 400:
        raise DeliveryError(f"API 取货失败 HTTP {resp.status_code}")
    path = cfg.get("result_path") or ""
    if not path:
        return resp.text.strip()
    data: Any = resp.json()
    for key in path.split("."):
        data = data[int(key)] if isinstance(data, list) else (data or {}).get(key)
    if not data:
        raise DeliveryError("API 返回中没有取到发货内容")
    return str(data)


async def deliver(order_pk: int, *, force: bool = False, user_id: int | None = None) -> bool:
    lock = _order_locks.setdefault(order_pk, asyncio.Lock())
    async with lock:
        return await _deliver(order_pk, force=force, user_id=user_id)


async def _deliver(order_pk: int, *, force: bool, user_id: int | None) -> bool:
    gateway = get_runtime().gateway
    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        if order is None:
            return False
        acc = await s.get(XyAccount, order.account_id)
        owner_id, settings = acc.owner_id, acc.get_settings()
        if order.status == OrderState.RISK_HOLD and force:
            await transition(s, order, OrderState.PAID)
        binding = await find_binding(s, order, owner_id)
        if binding is None:
            await s.commit()
            logger.info("订单 {} 的商品未绑定卡券，跳过自动发货", order.order_id)
            return False
        if not force:
            reason = await precheck(s, order, owner_id, binding)
            if reason:
                await transition(s, order, OrderState.RISK_HOLD, reason=reason)
                await s.commit()
                await _notify_owner(
                    order.account_id, NotifyEvents.DELIVERY_FAILED, f"🛑 订单 {order.order_id} 暂停自动发货", reason
                )
                return False
        if not await transition(s, order, OrderState.DELIVERING):
            await s.commit()
            return False
        await s.commit()
        pool = await s.get(CardPool, binding.pool_id)
        record = DeliveryRecord(order_pk=order.id, pool_id=pool.id if pool else None, mode=settings.delivery_mode)
        # 重试时：之前已经发给买家的内容 / 已完成的确认发货不再重复
        prior = list((await s.execute(select(DeliveryRecord).where(DeliveryRecord.order_pk == order.id))).scalars())
        already_sent = any(r.message_sent for r in prior)
        already_consigned = any(r.consigned for r in prior)
        record.message_sent, record.consigned = already_sent, already_consigned
        try:
            if pool is None:
                raise DeliveryError("卡券不存在")
            reused = None
            if already_sent:
                reused = (
                    await s.execute(
                        select(CardItem).where(CardItem.order_pk == order.id, CardItem.status == "locked").limit(1)
                    )
                ).scalar_one_or_none()
            if already_sent:
                content = get_vault().decrypt(reused.content_enc) if reused else ""
                card_id = reused.id if reused else None
            else:
                content, card_id = await allocate(s, pool, order)
            record.card_item_id = card_id
            record.preview = (content[:4] + "***") if content else ""
            await s.commit()
        except (DeliveryError, httpx.HTTPError, ValueError, KeyError) as e:
            await s.rollback()
            return await _fail(order_pk, str(e), record, release_card=None)
        text = _render(binding.template or DEFAULT_TEMPLATE, order, content)
        delay = binding.delay_seconds
        account_id, order_id, cid, buyer_id, item_id = (
            order.account_id,
            order.order_id,
            order.cid,
            order.buyer_id,
            order.item_id,
        )

    if delay:
        await asyncio.sleep(delay)

    async def send_message() -> None:
        conv = await message_service.find_conversation(account_id, cid=cid) if cid else None
        if conv is None:
            conv = await message_service.find_conversation(account_id, peer_id=buyer_id, item_id=item_id)
        if conv is None:
            raise DeliveryError("找不到与买家的会话，无法发送发货内容")
        await message_service.send_text(conv.id, text, source=MessageSource.DELIVERY, meta={"order_id": order_id})
        record.message_sent = True

    async def consign() -> None:
        await gateway.consign_virtual(account_id, order_id)
        record.consigned = True

    steps = {
        "confirm_then_send": [consign, send_message],
        "send_then_confirm": [send_message, consign],
        "send_only": [send_message],
    }[settings.delivery_mode]
    steps = [
        step
        for step in steps
        if not (step is send_message and record.message_sent) and not (step is consign and record.consigned)
    ]
    try:
        for step in steps:
            await step()
    except (DeliveryError, GoofishError, ConnectionError, ValueError) as e:
        # 内容尚未送达买家时释放卡密；已送达则保留占用，避免同一卡密发给两个人
        release = record.card_item_id if not record.message_sent else None
        return await _fail(order_pk, str(e), record, release_card=release)

    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        await transition(s, order, OrderState.DELIVERED)
        order.delivered_at = datetime.now(UTC)
        order.fail_reason = None
        order.next_retry_at = None
        if record.card_item_id:
            await s.execute(
                update(CardItem)
                .where(CardItem.id == record.card_item_id)
                .values(status="used", used_at=datetime.now(UTC))
            )
        record.success = True
        s.add(record)
        await s.commit()
    await record_audit(
        "order.deliver",
        user_id=user_id,
        actor_type="human" if user_id else "rule",
        account_id=account_id,
        target_type="order",
        target_id=order_id,
        detail={"mode": settings.delivery_mode, "pool_id": record.pool_id},
    )
    if pool and pool.kind == "pool":
        await check_stock(pool.id)
    return True


async def _fail(order_pk: int, error: str, record: DeliveryRecord, *, release_card: int | None) -> bool:
    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        if release_card:
            await s.execute(
                update(CardItem).where(CardItem.id == release_card).values(status="available", order_pk=None)
            )
        record.error = error[:500]
        s.add(record)
        await transition(s, order, OrderState.DELIVER_FAILED, reason=error[:500])
        order.retry_count += 1
        manual = order.retry_count > len(RETRY_DELAYS) or "库存不足" in error
        if manual:
            await transition(s, order, OrderState.MANUAL)
            order.next_retry_at = None
        else:
            order.next_retry_at = datetime.now(UTC) + timedelta(seconds=RETRY_DELAYS[order.retry_count - 1])
        await s.commit()
        account_id, order_id = order.account_id, order.order_id
    logger.warning("订单 {} 发货失败：{}", order_id, error)
    if manual:
        await bus.publish(Topics.DELIVERY_FAILED, {"account_id": account_id, "order_pk": order_pk})
        await _notify_owner(
            account_id, NotifyEvents.DELIVERY_FAILED, f"❌ 订单 {order_id} 自动发货失败", f"{error}\n已转为人工处理。"
        )
    return False


async def retry_failed() -> None:
    now = datetime.now(UTC)
    async with session_factory()() as s:
        rows = (await s.execute(select(Order).where(Order.status == OrderState.DELIVER_FAILED))).scalars()
        due = [o.id for o in rows if o.next_retry_at and _aware(o.next_retry_at) <= now]
    for order_pk in due:
        await deliver(order_pk)


async def check_stock(pool_id: int) -> None:
    async with session_factory()() as s:
        pool = await s.get(CardPool, pool_id)
        left = (
            await s.execute(
                select(func.count())
                .select_from(CardItem)
                .where(CardItem.pool_id == pool_id, CardItem.status == "available")
            )
        ).scalar_one()
        owner_id, name, threshold = pool.owner_id, pool.name, pool.low_stock_threshold
    if left <= threshold:
        await notify(
            owner_id,
            Notification(
                event=NotifyEvents.STOCK_LOW,
                title=f"📦 卡券「{name}」库存不足",
                content=f"剩余 {left} 张，请及时补充。",
            ),
        )


# ---------------------------------------------------------------- 同步 / 评价
async def sync_orders(account_id: int, pages: int = 2) -> dict[str, int]:
    gateway = get_runtime().gateway
    created = paid = 0
    to_handle: list[int] = []
    for page in range(1, pages + 1):
        orders, more = await gateway.list_sold_orders(account_id, page)
        async with session_factory()() as s:
            for remote in orders:
                order, is_new = await upsert_order(s, account_id, remote.order_id)
                created += int(is_new)
                _apply_remote(order, remote)
                if remote.created_at and order.created_at is None:
                    order.created_at = remote.created_at
                local = _REMOTE_TO_LOCAL.get(remote.status)
                if local == OrderState.PAID and order.status == OrderState.PENDING_PAY:
                    to_handle.append(order.id)
                    paid += 1
                elif local and local != OrderState.PAID:
                    await transition(s, order, local)
            await s.commit()
        if not more:
            break
    for order_pk in to_handle:
        await handle_paid(order_pk)
    return {"created": created, "paid": paid}


async def sync_all_auto_delivery() -> None:
    async with session_factory()() as s:
        accounts = [
            a.id
            for a in (await s.execute(select(XyAccount))).scalars()
            if a.get_settings().auto_delivery and a.status == "active"
        ]
    for account_id in accounts:
        try:
            await sync_orders(account_id, pages=1)
        except GoofishError as e:
            logger.warning("订单同步失败 account={} err={}", account_id, e)


async def maybe_rate(order_pk: int) -> None:
    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        acc = await s.get(XyAccount, order.account_id)
        settings = acc.get_settings()
        if not settings.auto_rate or order.rated:
            return
        account_id, order_id = order.account_id, order.order_id
    try:
        await get_runtime().gateway.rate_order(account_id, order_id, settings.rate_text)
    except GoofishError as e:
        logger.warning("自动评价失败 order={} err={}", order_id, e)
        return
    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        order.rated = True
        await s.commit()


async def _notify_owner(account_id: int, event: str, title: str, content: str) -> None:
    async with session_factory()() as s:
        acc = await s.get(XyAccount, account_id)
        owner_id = acc.owner_id if acc else None
    await notify(owner_id, Notification(event=event, title=title, content=content))
