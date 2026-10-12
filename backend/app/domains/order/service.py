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
from sqlalchemy import and_, func, or_, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import get_vault
from app.core.db import session_factory
from app.core.events import Topics, bus
from app.core.netguard import UnsafeTargetError, check_url, owner_may_use_private
from app.core.realtime import hub
from app.domains.account.models import XyAccount
from app.domains.goods.models import MyItem
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
from app.notify.service import NotifyEvents, notify_background
from app.runtime import get_runtime

RETRY_DELAYS = [60, 120, 300, 600]  # 秒
DEFAULT_TEMPLATE = "您好，订单已发货，内容如下：\n{content}\n如有问题请随时联系～"
NO_BINDING_REASON = "该商品还没有关联发货内容，请在「订单发货 → 自动发货 → 商品关联」中设置后再发货"
_order_locks: dict[int, asyncio.Lock] = {}
_precheck_lock = asyncio.Lock()
_push_tasks: set[asyncio.Task] = set()


class DeliveryError(Exception):
    pass


class DeliveryInterrupted(Exception):
    """发货过程中订单被关闭 / 退款 / 人工接管：停止后续步骤。"""

    def __init__(self, status: str) -> None:
        super().__init__(status)
        self.status = status


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
    values: dict[str, Any] = {"status": to}
    now = datetime.now(UTC)
    if to in (OrderState.DELIVERED, OrderState.COMPLETED):
        if not order.paid_at:
            order.paid_at = order.created_at or now
            values["paid_at"] = order.paid_at
        if to == OrderState.DELIVERED and not order.delivered_at:
            order.delivered_at = now
            values["delivered_at"] = order.delivered_at
        # 订单履约成功：若此前发货重试锁定了卡密，同步转为已使用
        await s.execute(
            update(CardItem)
            .where(CardItem.order_pk == order.id, CardItem.status == "locked")
            .values(status="used", used_at=now)
        )
    elif to in (OrderState.CLOSED, OrderState.REFUNDED) and not await _card_may_be_out(s, order):
        # 订单关闭 / 退款 / 取消：若有未完成发货的锁定卡密，自动释放回库存
        await s.execute(
            update(CardItem)
            .where(CardItem.order_pk == order.id, CardItem.status == "locked")
            .values(status="available", order_pk=None)
        )
    if reason is not None:
        order.fail_reason = reason
        values["fail_reason"] = reason
    result = await s.execute(update(Order).where(Order.id == order.id, Order.status == order.status).values(**values))
    if result.rowcount != 1:
        return False  # 并发下已被其他流程改变
    order.status = to
    _spawn_push({"id": order.id, "order_id": order.order_id, "status": to}, order.account_id)
    return True


async def _card_may_be_out(s: AsyncSession, order: Order) -> bool:
    """卡密可能已经发给买家：正在发货中（由发货流程自己决定是否退回），或之前已有发出记录。"""
    if order.status == OrderState.DELIVERING:
        return True
    sent = await s.execute(
        select(DeliveryRecord.id).where(DeliveryRecord.order_pk == order.id, DeliveryRecord.message_sent.is_(True))
    )
    return sent.first() is not None


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


async def handle_paid(order_pk: int, *, confirmed: bool = False) -> None:
    """confirmed=True 表示已从闲鱼订单列表确认已付款（订单同步）。
    来自聊天里的付款通知时不可信（买家可以手打一段伪造的通知），必须由订单详情确认已付款才发货。"""
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
        if not confirmed and (remote is None or remote.status != OrderStatus.PAID):
            # 没从闲鱼确认已付款：不发货，交给订单同步核实（真付款的订单下一轮同步会补发）
            logger.warning(
                "付款通知未经闲鱼确认，暂不发货 order={} remote={}",
                order_id,
                remote.status_text if remote else "查询失败",
            )
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
        self_ship = order.id in await self_ship_order_ids(s, [order])
    await bus.publish(Topics.ORDER_PAID, {"account_id": account_id, "order_pk": order_pk})
    if self_ship:
        # 实物商品：网页端没有填运单号发货的功能，提醒卖家去 App 发货（推送里不带收货地址）
        await _notify_owner(
            account_id,
            NotifyEvents.ORDER_PAID,
            f"📦 实物订单待发货：{title}",
            f"金额：{amount}　订单号：{order_id}\n买家已付款，请尽快在闲鱼 App 里发货；"
            "收货信息和扫码去发货在管理台「订单管理」里查看。",
        )
    else:
        await _notify_owner(
            account_id, NotifyEvents.ORDER_PAID, f"💰 新订单已付款：{title}", f"金额：{amount}　订单号：{order_id}"
        )
    if settings.auto_delivery:
        await deliver(order_pk)


# ---------------------------------------------------------------- 实物订单：卖家自己发货
# 网页端没有填运单号发货的接口，只能在闲鱼 App 发货。这里负责识别、提醒和提供收货信息。
SHIP_REMIND_AFTER = timedelta(hours=24)
DELIVER_PAGE = (
    "https://h5.m.goofish.com/wow/moyu/moyu-project/idle-logistics/pages/idleDeliver"
    "?kun=true&titleVisible=false&useCusFont=true&orderId={order_id}"
)


async def self_ship_order_ids(s: AsyncSession, orders: list[Order]) -> set[int]:
    """已付款、商品不是虚拟商品、也没有关联发货内容：需要卖家自己寄出的订单。"""
    paid = [o for o in orders if o.status == OrderState.PAID and o.item_id]
    if not paid:
        return set()
    owners = dict(
        (
            await s.execute(
                select(XyAccount.id, XyAccount.owner_id).where(XyAccount.id.in_({o.account_id for o in paid}))
            )
        ).all()
    )
    item_ids = {o.item_id for o in paid}
    bindings = (
        await s.execute(
            select(CardBinding.owner_id, CardBinding.item_id, CardBinding.account_id).where(
                CardBinding.item_id.in_(item_ids)
            )
        )
    ).all()
    virtual = {
        (a, i)
        for a, i in (
            await s.execute(
                select(MyItem.account_id, MyItem.item_id).where(
                    MyItem.item_id.in_(item_ids), MyItem.is_virtual.is_(True)
                )
            )
        ).all()
    }
    out = set()
    for o in paid:
        if (o.account_id, o.item_id) in virtual:
            continue
        owner = owners.get(o.account_id)
        if any(
            b_owner == owner and b_item == o.item_id and b_acc in (None, o.account_id)
            for b_owner, b_item, b_acc in bindings
        ):
            continue
        out.add(o.id)
    return out


async def remind_unshipped() -> int:
    """实物订单付款超过 24 小时仍未发货：提醒一次，避免超时被投诉。"""
    cutoff = datetime.now(UTC) - SHIP_REMIND_AFTER
    async with session_factory()() as s:
        candidates = list(
            (
                await s.execute(
                    select(Order).where(
                        Order.status == OrderState.PAID, Order.ship_reminded_at.is_(None), Order.paid_at.is_not(None)
                    )
                )
            ).scalars()
        )
        due = [o for o in candidates if _aware(o.paid_at) <= cutoff]
        targets = [o for o in due if o.id in await self_ship_order_ids(s, due)]
        for o in targets:
            o.ship_reminded_at = datetime.now(UTC)
        await s.commit()
        items = [(o.account_id, o.order_id, o.item_title or o.item_id) for o in targets]
    for account_id, order_id, title in items:
        await _notify_owner(
            account_id,
            NotifyEvents.ORDER_PAID,
            f"⏰ 实物订单超过 24 小时未发货：{title}",
            f"订单号：{order_id}\n买家付款已超过 24 小时，请尽快在闲鱼 App 里发货，避免超时被投诉。",
        )
    return len(items)


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
                        or_(
                            and_(
                                Order.status.in_([OrderState.DELIVERED, OrderState.COMPLETED]),
                                Order.delivered_at >= since,
                            ),
                            # 正在发货的也算：同一买家同时付款的两单不能都放行
                            and_(Order.status == OrderState.DELIVERING, Order.id != order.id),
                        ),
                    )
                )
            ).scalar_one()
            if n >= binding.max_per_buyer:
                return f"同一买家 24 小时内已发货 {n} 次（跨账号统计）"
    return None


async def allocate(s: AsyncSession, pool: CardPool, order: Order) -> tuple[str, int | None]:
    """返回 (内容, card_item_id)。卡密库存通过条件更新原子出库。"""
    if not pool.enabled:
        raise DeliveryError("发货内容已停用")
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
        allow_private = await owner_may_use_private(pool.owner_id)
        return await call_delivery_api(pool.api_config, order, allow_private=allow_private), None
    raise DeliveryError(f"未知的发货方式 {pool.kind}")


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
    # 发货内容的常见写法都认：{content}（标准）、{card}、{卡密}
    for alias in ("{card}", "{卡密}"):
        out = out.replace(alias, "{content}")
    has_slot = "{content}" in out
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    if content and not has_slot:
        # 模板里没有内容占位符：附在末尾，保证买家一定能收到付款购买的内容
        out = f"{out.rstrip()}\n{content}"
    return out


async def call_delivery_api(cfg: dict[str, Any], order: Order, *, allow_private: bool = False) -> str:
    url = cfg.get("url", "")
    try:
        await check_url(url, allow_private=allow_private)
    except UnsafeTargetError as e:
        raise DeliveryError(f"API 取货地址无效：{e}") from e
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
            if force:
                # 人工点「手动发货」：记录原因，前端据此提示去关联
                order.fail_reason = NO_BINDING_REASON
                await s.commit()
                return False
            # 标记为虚拟商品却没有关联发货内容：大概率是忘了设置，转人工并提醒；
            # 实物商品本来就需要卖家自己发货，保持「已付款」不打扰
            is_virtual = (
                await s.execute(
                    select(MyItem.is_virtual).where(
                        MyItem.account_id == order.account_id, MyItem.item_id == order.item_id
                    )
                )
            ).scalar_one_or_none()
            moved = bool(is_virtual) and await transition(s, order, OrderState.MANUAL, reason=NO_BINDING_REASON)
            await s.commit()
            logger.info("订单 {} 的商品未关联发货内容，跳过自动发货", order.order_id)
            if moved:
                await _notify_owner(
                    order.account_id,
                    NotifyEvents.DELIVERY_FAILED,
                    f"⚠️ 订单 {order.order_id} 没有自动发货",
                    f"商品「{order.item_title or order.item_id}」标记为虚拟商品，但还没有关联发货内容。"
                    "订单已转为待人工，请在「订单发货 → 自动发货 → 商品关联」中设置后手动发货。",
                )
            return False
        # 限购检查到标记「发货中」之间串行：否则同一买家并发的两单会同时通过检查
        async with _precheck_lock:
            reason = None if force else await precheck(s, order, owner_id, binding)
            if reason:
                await transition(s, order, OrderState.RISK_HOLD, reason=reason)
            moved = reason is None and await transition(s, order, OrderState.DELIVERING)
            await s.commit()
        if reason:
            await _notify_owner(
                order.account_id, NotifyEvents.DELIVERY_FAILED, f"🛑 订单 {order.order_id} 暂停自动发货", reason
            )
            return False
        if not moved:
            return False
        pool = await s.get(CardPool, binding.pool_id)
        record = DeliveryRecord(order_pk=order.id, pool_id=pool.id if pool else None, mode=settings.delivery_mode)
        # 重试时：之前已经发给买家的内容 / 已完成的确认发货不再重复
        prior = list((await s.execute(select(DeliveryRecord).where(DeliveryRecord.order_pk == order.id))).scalars())
        already_sent = any(r.message_sent for r in prior)
        already_consigned = any(r.consigned for r in prior)
        record.message_sent, record.consigned = already_sent, already_consigned
        try:
            if pool is None:
                raise DeliveryError("发货内容不存在")
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
        relist = binding.auto_relist
        images = list(pool.images or [])
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
        if images:
            # 文字（含卡密）已经送达：图片失败只提醒卖家补发，不让整单失败重试（否则会重复发卡密）
            try:
                await message_service.send_images(
                    conv.id, images, source=MessageSource.DELIVERY, meta={"order_id": order_id}
                )
            except Exception as e:  # noqa: BLE001
                logger.warning("订单 {} 的发货图片没有发出去：{}", order_id, e)
                await _notify_owner(
                    account_id,
                    NotifyEvents.DELIVERY_FAILED,
                    f"⚠️ 订单 {order_id} 的发货图片没有发出去",
                    f"发货文字已经发给买家，但图片发送失败（{_describe(e)}），请在聊天里手动补发图片。",
                )

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
    current = None
    try:
        for step in steps:
            current = step
            # 等待延迟 / 上一步期间订单可能被关闭或退款：每一步前都重新确认还在「发货中」
            status = await _order_status(order_pk)
            if status != OrderState.DELIVERING:
                raise DeliveryInterrupted(status)
            await step()
    except DeliveryInterrupted as e:
        return await _interrupted(order_pk, record, e.status)
    except Exception as e:  # noqa: BLE001  任何异常都要落到失败处理，订单不能卡在「发货中」
        if current is send_message and not record.message_sent and _maybe_sent(e):
            # 发出去了但没等到回执：可能已经送达，不退回卡密、不自动重试（否则会再发一张）
            return await _fail(
                order_pk,
                f"发送发货消息时{_describe(e)}，消息可能已送达买家，请先在聊天里核对后再处理",
                record,
                release_card=None,
                manual=True,
            )
        # 内容尚未送达买家时释放卡密；已送达则保留占用，避免同一卡密发给两个人
        release = record.card_item_id if not record.message_sent else None
        return await _fail(order_pk, _describe(e), record, release_card=release)

    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        # 只从「发货中」迁移：期间转成退款中 / 已关闭的订单不能被「已发货」覆盖
        delivered = order.status == OrderState.DELIVERING and await transition(s, order, OrderState.DELIVERED)
        final_status = order.status
        if delivered:
            order.delivered_at = datetime.now(UTC)
            order.fail_reason = None
            order.next_retry_at = None
        card_ok = True
        if record.card_item_id:
            card_ok = (
                await s.execute(
                    update(CardItem)
                    .where(
                        CardItem.id == record.card_item_id,
                        CardItem.order_pk == order_pk,
                        CardItem.status.in_(("locked", "used")),
                    )
                    .values(status="used", used_at=datetime.now(UTC))
                )
            ).rowcount == 1
        record.success = delivered
        if not delivered:
            record.error = f"发货内容已发出，但订单在发货过程中变为「{final_status}」"
        s.add(record)
        await s.commit()
    if not card_ok:
        logger.error("订单 {} 发出的卡密 {} 已不归本单所有，可能重复发放", order_id, record.card_item_id)
        await _notify_owner(
            account_id,
            NotifyEvents.DELIVERY_FAILED,
            f"⚠️ 订单 {order_id} 的卡密可能重复发放",
            "发货内容已经发给买家，但这张卡密已被释放或分配给其他订单，请核对后处理。",
        )
    if not delivered:
        await _notify_owner(
            account_id,
            NotifyEvents.DELIVERY_FAILED,
            f"⚠️ 订单 {order_id} 发货期间状态有变",
            f"发货内容已经发给买家，但订单在此期间变为「{final_status}」，没有标记为已发货，请人工核对。",
        )
        return False
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
    if relist and item_id:
        _spawn(_relist_later(account_id, item_id))
    return True


RELIST_DELAY_SECONDS = 15  # 等闲鱼把卖完的商品状态更新为下架
_tasks: set[asyncio.Task] = set()


def _spawn(coro) -> None:  # noqa: ANN001
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)


async def _relist_later(account_id: int, item_id: str) -> None:
    from app.domains.goods.service import relist_sold_item
    from app.goofish.errors import VerificationRequiredError

    await asyncio.sleep(RELIST_DELAY_SECONDS)
    try:
        await relist_sold_item(account_id, item_id)
    except Exception as e:  # noqa: BLE001  后台任务：失败要告诉卖家，否则商品下架了没人知道
        logger.exception("商品 {} 自动重新上架失败", item_id)
        reason = (
            "闲鱼要求先完成身份认证，请到「商品 → 发布」发布一次并按提示扫码认证"
            if isinstance(e, VerificationRequiredError)
            else str(e) or type(e).__name__
        )
        await _notify_owner(
            account_id,
            NotifyEvents.ITEM_RELISTED,
            f"⚠️ 商品 {item_id} 卖完了，但自动重新上架失败",
            f"{reason}\n商品现已下架，请手动重新发布。",
        )


# 能确定消息没有发出去的错误（发送前就被拒绝）；其余如超时、发出后断线都算「可能已送达」
_NOT_SENT_ERRORS = ("IM 未连接", "该账号 IM 未连接", "IM 网关未运行", "发送失败")


def _maybe_sent(e: BaseException) -> bool:
    if isinstance(e, DeliveryError | ValueError | GoofishError):
        return False
    if isinstance(e, ConnectionError | RuntimeError) and str(e).startswith(_NOT_SENT_ERRORS):
        return False
    return True


def _describe(e: BaseException) -> str:
    if isinstance(e, TimeoutError):
        return "等待闲鱼回执超时"
    return str(e) or type(e).__name__


async def _order_status(order_pk: int) -> str | None:
    async with session_factory()() as s:
        return (await s.execute(select(Order.status).where(Order.id == order_pk))).scalar_one_or_none()


async def _release_card(s: AsyncSession, card_id: int, order_pk: int) -> None:
    # 只释放仍由本单锁定的卡密：已用掉或已归其他订单的不能动
    await s.execute(
        update(CardItem)
        .where(CardItem.id == card_id, CardItem.order_pk == order_pk, CardItem.status == "locked")
        .values(status="available", order_pk=None)
    )


async def _interrupted(order_pk: int, record: DeliveryRecord, status: str | None) -> bool:
    """发货途中订单不再是「发货中」：不再继续发，也不改订单状态。"""
    async with session_factory()() as s:
        if record.card_item_id and not record.message_sent:
            await _release_card(s, record.card_item_id, order_pk)  # 买家还没收到：卡密退回库存
        record.error = f"订单已变为「{status}」，停止发货"
        s.add(record)
        await s.commit()
        order = await s.get(Order, order_pk)
        account_id, order_id = order.account_id, order.order_id
    logger.info("订单 {} 在发货过程中变为 {}，停止发货", order_id, status)
    if record.message_sent:
        await _notify_owner(
            account_id,
            NotifyEvents.DELIVERY_FAILED,
            f"⚠️ 订单 {order_id} 发货期间状态有变",
            f"发货内容已经发给买家，但订单随后变为「{status}」，没有继续确认发货，请人工核对。",
        )
    return False


async def _fail(
    order_pk: int, error: str, record: DeliveryRecord, *, release_card: int | None, manual: bool = False
) -> bool:
    async with session_factory()() as s:
        order = await s.get(Order, order_pk)
        if release_card:
            await _release_card(s, release_card, order_pk)
        record.error = error[:500]
        s.add(record)
        await transition(s, order, OrderState.DELIVER_FAILED, reason=error[:500])
        order.retry_count += 1
        manual = manual or order.retry_count > len(RETRY_DELAYS) or "库存不足" in error
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


STUCK_AFTER = timedelta(minutes=10)


async def recover_stuck_deliveries() -> int:
    """「发货中」超过 10 分钟仍未结束（进程重启 / 异常中断）：转人工并提醒核对，卡密保持占用不复用。"""
    cutoff = datetime.now(UTC) - STUCK_AFTER
    moved: list[tuple[int, str]] = []
    async with session_factory()() as s:
        rows = (await s.execute(select(Order).where(Order.status == OrderState.DELIVERING))).scalars()
        for order in rows:
            lock = _order_locks.get(order.id)
            if (lock and lock.locked()) or _aware(order.updated_at) > cutoff:
                continue  # 本进程正在发这一单，或还没到超时
            reason = "发货过程中断（服务重启或异常），消息可能已发出，请在聊天里核对后再处理"
            if await transition(s, order, OrderState.MANUAL, reason=reason):
                moved.append((order.account_id, order.order_id))
        await s.commit()
    for account_id, order_id in moved:
        await _notify_owner(
            account_id,
            NotifyEvents.DELIVERY_FAILED,
            f"⚠️ 订单 {order_id} 发货中断",
            "发货过程中断，消息可能已发给买家。已转为人工处理，请先在聊天里核对。",
        )
    return len(moved)


PAID_PICKUP_AFTER = timedelta(minutes=2)
PAID_PICKUP_WINDOW = timedelta(hours=6)


async def recover_paid_orders() -> int:
    """已确认付款、开了自动发货、有发货关联，却还停在「已付款」的订单（付款后、发货前进程重启或任务被取消）：补发。
    只补最近 6 小时内付款的，免得刚打开自动发货就把很早以前的订单一股脑发出去。"""
    now = datetime.now(UTC)
    due: list[int] = []
    async with session_factory()() as s:
        rows = list(
            (
                await s.execute(select(Order).where(Order.status == OrderState.PAID, Order.paid_at.is_not(None)))
            ).scalars()
        )
        accounts: dict[int, XyAccount | None] = {}
        for order in rows:
            if not (now - PAID_PICKUP_WINDOW <= _aware(order.paid_at) <= now - PAID_PICKUP_AFTER):
                continue
            if order.account_id not in accounts:
                accounts[order.account_id] = await s.get(XyAccount, order.account_id)
            acc = accounts[order.account_id]
            if acc is None or acc.status != "active" or not acc.get_settings().auto_delivery:
                continue
            if await find_binding(s, order, acc.owner_id) is not None:
                due.append(order.id)
    for order_pk in due:
        logger.info("订单 {} 已付款但没有发货，补发", order_pk)
        await deliver(order_pk)
    return len(due)


async def retry_failed() -> None:
    await recover_stuck_deliveries()
    await recover_paid_orders()
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
        # 低库存时每单发货都会走到这里，同一发货内容 1 小时内只提醒一次
        notify_background(
            owner_id,
            Notification(
                event=NotifyEvents.STOCK_LOW,
                title=f"📦 发货内容「{name}」卡密库存不足",
                content=f"剩余 {left} 张，请及时补充。",
            ),
            dedupe_key=f"stock_low:{pool_id}",
            cooldown=3600,
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
        await handle_paid(order_pk, confirmed=True)
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
        except Exception:  # noqa: BLE001  一个账号出错不能让其余账号的付款都漏同步
            logger.exception("订单同步异常 account={}", account_id)


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
    # 后台发送：付款后紧接着就要自动发货，不能等慢渠道超时
    notify_background(owner_id, Notification(event=event, title=title, content=content))
