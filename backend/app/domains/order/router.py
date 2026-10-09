from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.core.crypto import get_vault
from app.core.deps import CurrentUser, SessionDep
from app.core.pagination import set_total
from app.domains.account.service import accessible_account_ids, get_account_for
from app.domains.buyer.pipeline import load_seller_profile
from app.domains.message.models import ChatMessage, Conversation
from app.domains.order import service
from app.domains.order.buyer_risk import BuyerAnalysis, BuyerInsightOut, ShopHistory, analyze_buyer, buyer_insight
from app.domains.order.models import (
    ORDER_STATE_LABELS,
    BuyerBlacklist,
    CardBinding,
    CardItem,
    CardPool,
    DeliveryRecord,
    Order,
    OrderState,
)
from app.domains.system.audit import record_audit
from app.goofish.errors import GoofishError
from app.intelligence.llm import LLMError, LLMUnavailable, get_llm

router = APIRouter(tags=["orders"])


class OrderOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    order_id: str
    item_id: str | None
    item_title: str
    buyer_id: str | None
    buyer_nick: str
    amount: float | None
    quantity: int
    spec_name: str
    spec_value: str
    status: str
    remote_status: str
    is_bargain: bool
    paid_at: datetime | None
    delivered_at: datetime | None
    fail_reason: str | None
    retry_count: int
    created_at: datetime


class PoolIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = Field(pattern="^(text|pool|api)$")
    text: str | None = None
    api_config: dict[str, Any] = Field(default_factory=dict)
    low_stock_threshold: int = 5
    enabled: bool = True


class PoolOut(BaseModel):
    id: int
    name: str
    kind: str
    text_preview: str | None
    api_config: dict[str, Any]
    low_stock_threshold: int
    enabled: bool
    stock: dict[str, int]


class ImportIn(BaseModel):
    lines: str = Field(min_length=1, description="每行一张卡密")


class BindingIn(BaseModel):
    pool_id: int
    account_id: int | None = None
    item_id: str
    spec_value: str | None = None
    template: str = ""
    delay_seconds: int = Field(default=0, ge=0, le=600)
    max_per_buyer: int = Field(default=0, ge=0)


class BindingOut(BindingIn):
    model_config = {"from_attributes": True}

    id: int


class BlacklistIn(BaseModel):
    buyer_id: str
    reason: str = ""


def _preview(text: str | None) -> str | None:
    if text is None:
        return None
    return text[:12] + ("…" if len(text) > 12 else "")


async def _own_order(session, user, order_pk: int) -> Order:
    order = await session.get(Order, order_pk)
    if order is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "订单不存在")
    await get_account_for(session, user, order.account_id)
    return order


async def _own_pool(session, user, pool_id: int) -> CardPool:
    pool = await session.get(CardPool, pool_id)
    if pool is None or pool.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "发货内容不存在")
    return pool


async def _pool_out(session, pool: CardPool) -> PoolOut:
    rows = await session.execute(
        select(CardItem.status, func.count()).where(CardItem.pool_id == pool.id).group_by(CardItem.status)
    )
    stock = {"available": 0, "locked": 0, "used": 0}
    stock.update({k: v for k, v in rows})
    return PoolOut(
        id=pool.id,
        name=pool.name,
        kind=pool.kind,
        text_preview=_preview(get_vault().decrypt(pool.text_enc)) if pool.text_enc else None,
        api_config={k: ("***" if k == "headers" else v) for k, v in (pool.api_config or {}).items()},
        low_stock_threshold=pool.low_stock_threshold,
        enabled=pool.enabled,
        stock=stock,
    )


# ---------------------------------------------------------------- 订单
@router.get("/orders", response_model=list[OrderOut])
async def list_orders(
    user: CurrentUser,
    session: SessionDep,
    response: Response,
    account_id: int | None = None,
    status_: str | None = Query(None, alias="status"),
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[Order]:
    ids = await accessible_account_ids(session, user)
    stmt = select(Order).order_by(Order.id.desc())
    if ids is not None:
        stmt = stmt.where(Order.account_id.in_(ids))
    if account_id is not None:
        stmt = stmt.where(Order.account_id == account_id)
    if status_:
        # 支持逗号分隔的多个状态，例如 manual,risk_hold,deliver_failed（总览「待人工处理」）
        statuses = [st for st in status_.split(",") if st]
        stmt = stmt.where(Order.status.in_(statuses))
    if q:
        stmt = stmt.where(Order.order_id.contains(q) | Order.item_title.contains(q) | Order.buyer_nick.contains(q))
    await set_total(response, session, stmt)
    return list((await session.execute(stmt.limit(limit).offset(offset))).scalars())


@router.get("/orders/{order_pk}")
async def get_order(order_pk: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    order = await _own_order(session, user, order_pk)
    records = await session.execute(
        select(DeliveryRecord).where(DeliveryRecord.order_pk == order.id).order_by(DeliveryRecord.id)
    )
    return {
        "order": OrderOut.model_validate(order).model_dump(),
        "deliveries": [
            {
                "id": r.id,
                "mode": r.mode,
                "preview": r.preview,
                "message_sent": r.message_sent,
                "consigned": r.consigned,
                "success": r.success,
                "error": r.error,
                "created_at": r.created_at,
            }
            for r in records.scalars()
        ],
    }


@router.post("/orders/sync/{account_id}")
async def sync(account_id: int, user: CurrentUser, session: SessionDep) -> dict[str, int]:
    await get_account_for(session, user, account_id)
    try:
        return await service.sync_orders(account_id)
    except GoofishError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e


@router.post("/orders/{order_pk}/deliver")
async def manual_deliver(order_pk: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """人工触发发货（跳过发货前风控，适用于风控暂停 / 失败转人工的订单）。"""
    order = await _own_order(session, user, order_pk)
    if order.status not in (OrderState.PAID, OrderState.RISK_HOLD, OrderState.DELIVER_FAILED, OrderState.MANUAL):
        label = ORDER_STATE_LABELS.get(order.status, order.status)
        raise HTTPException(status.HTTP_409_CONFLICT, f"订单当前为「{label}」，不能发货")
    ok = await service.deliver(order.id, force=True, user_id=user.id)
    await session.refresh(order)
    code = "no_binding" if not ok and order.fail_reason == service.NO_BINDING_REASON else None
    return {"ok": ok, "status": order.status, "error": order.fail_reason, "code": code, "item_id": order.item_id}


@router.post("/orders/{order_pk}/close-hold")
async def close_hold(order_pk: int, user: CurrentUser, session: SessionDep) -> dict[str, str]:
    order = await _own_order(session, user, order_pk)
    await service.transition(
        session, order, OrderState.MANUAL if order.status == OrderState.RISK_HOLD else order.status
    )
    await session.commit()
    return {"status": order.status}


# ---------------------------------------------------------------- 卡券
@router.get("/cards/pools", response_model=list[PoolOut])
async def list_pools(user: CurrentUser, session: SessionDep) -> list[PoolOut]:
    pools = (await session.execute(select(CardPool).where(CardPool.owner_id == user.id))).scalars()
    return [await _pool_out(session, p) for p in pools]


@router.post("/cards/pools", response_model=PoolOut, status_code=201)
async def create_pool(body: PoolIn, user: CurrentUser, session: SessionDep) -> PoolOut:
    if body.kind == "text" and not body.text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "「固定内容」需要填写发货内容")
    if body.kind == "api" and not str(body.api_config.get("url", "")).startswith(("http://", "https://")):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "「接口取货」需要填写有效的 url")
    pool = CardPool(
        owner_id=user.id,
        name=body.name,
        kind=body.kind,
        text_enc=get_vault().encrypt(body.text) if body.text else None,
        api_config=body.api_config,
        low_stock_threshold=body.low_stock_threshold,
        enabled=body.enabled,
    )
    session.add(pool)
    await session.commit()
    return await _pool_out(session, pool)


@router.put("/cards/pools/{pool_id}", response_model=PoolOut)
async def update_pool(pool_id: int, body: PoolIn, user: CurrentUser, session: SessionDep) -> PoolOut:
    pool = await _own_pool(session, user, pool_id)
    pool.name, pool.low_stock_threshold, pool.enabled = body.name, body.low_stock_threshold, body.enabled
    if body.text:
        pool.text_enc = get_vault().encrypt(body.text)
    if body.api_config:
        headers = body.api_config.get("headers")
        pool.api_config = {
            **body.api_config,
            "headers": pool.api_config.get("headers") if headers == "***" else headers,
        }
    await session.commit()
    return await _pool_out(session, pool)


@router.delete("/cards/pools/{pool_id}", status_code=204)
async def delete_pool(pool_id: int, user: CurrentUser, session: SessionDep) -> None:
    pool = await _own_pool(session, user, pool_id)
    await session.delete(pool)
    await session.commit()


@router.post("/cards/pools/{pool_id}/items")
async def import_cards(pool_id: int, body: ImportIn, user: CurrentUser, session: SessionDep) -> dict[str, int]:
    pool = await _own_pool(session, user, pool_id)
    if pool.kind != "pool":
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只有「卡密库存」类型的发货内容可以导入卡密")
    lines = [line.strip() for line in body.lines.splitlines() if line.strip()]
    existing = {fp for (fp,) in await session.execute(select(CardItem.fingerprint).where(CardItem.pool_id == pool.id))}
    added = dup = 0
    vault = get_vault()
    for line in lines:
        fp = service.fingerprint(line)
        if fp in existing:
            dup += 1
            continue
        existing.add(fp)
        session.add(CardItem(pool_id=pool.id, content_enc=vault.encrypt(line), fingerprint=fp))
        added += 1
    await session.commit()
    await record_audit(
        "cards.import",
        user_id=user.id,
        actor_type="human",
        target_type="pool",
        target_id=pool.id,
        detail={"added": added, "duplicated": dup},
    )
    return {"added": added, "duplicated": dup}


@router.get("/cards/pools/{pool_id}/items")
async def list_cards(
    pool_id: int, user: CurrentUser, session: SessionDep, status_: str | None = Query(None, alias="status")
) -> list[dict[str, Any]]:
    pool = await _own_pool(session, user, pool_id)
    stmt = select(CardItem).where(CardItem.pool_id == pool.id).order_by(CardItem.id.desc()).limit(500)
    if status_:
        stmt = stmt.where(CardItem.status == status_)
    vault = get_vault()
    out = []
    for c in (await session.execute(stmt)).scalars():
        plain = vault.decrypt(c.content_enc) or ""
        out.append(
            {
                "id": c.id,
                "masked": plain[:3] + "***" + plain[-2:] if len(plain) > 6 else "***",
                "status": c.status,
                "order_pk": c.order_pk,
                "used_at": c.used_at,
            }
        )
    return out


@router.delete("/cards/items/{card_id}", status_code=204)
async def delete_card(card_id: int, user: CurrentUser, session: SessionDep) -> None:
    card = await session.get(CardItem, card_id)
    if card is None:
        return
    await _own_pool(session, user, card.pool_id)
    if card.status != "available":
        raise HTTPException(status.HTTP_409_CONFLICT, "已占用 / 已使用的卡密不能删除")
    await session.delete(card)
    await session.commit()


@router.get("/cards/bindings", response_model=list[BindingOut])
async def list_bindings(user: CurrentUser, session: SessionDep) -> list[CardBinding]:
    return list((await session.execute(select(CardBinding).where(CardBinding.owner_id == user.id))).scalars())


@router.post("/cards/bindings", response_model=BindingOut, status_code=201)
async def create_binding(body: BindingIn, user: CurrentUser, session: SessionDep) -> CardBinding:
    await _own_pool(session, user, body.pool_id)
    if body.account_id is not None:
        await get_account_for(session, user, body.account_id)
    b = CardBinding(owner_id=user.id, **body.model_dump())
    session.add(b)
    await session.commit()
    return b


@router.put("/cards/bindings/{binding_id}", response_model=BindingOut)
async def update_binding(binding_id: int, body: BindingIn, user: CurrentUser, session: SessionDep) -> CardBinding:
    b = await session.get(CardBinding, binding_id)
    if b is None or b.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "绑定不存在")
    await _own_pool(session, user, body.pool_id)
    if body.account_id is not None:
        await get_account_for(session, user, body.account_id)
    for k, v in body.model_dump().items():
        setattr(b, k, v)
    await session.commit()
    return b


@router.delete("/cards/bindings/{binding_id}", status_code=204)
async def delete_binding(binding_id: int, user: CurrentUser, session: SessionDep) -> None:
    b = await session.get(CardBinding, binding_id)
    if b and b.owner_id == user.id:
        await session.delete(b)
        await session.commit()


# ---------------------------------------------------------------- 黑名单
@router.get("/orders-blacklist")
async def list_blacklist(user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    rows = await session.execute(select(BuyerBlacklist).where(BuyerBlacklist.owner_id == user.id))
    return [
        {"id": r.id, "buyer_id": r.buyer_id, "reason": r.reason, "created_at": r.created_at} for r in rows.scalars()
    ]


@router.post("/orders-blacklist", status_code=201)
async def add_blacklist(body: BlacklistIn, user: CurrentUser, session: SessionDep) -> dict[str, str]:
    exists = (
        await session.execute(
            select(BuyerBlacklist).where(BuyerBlacklist.owner_id == user.id, BuyerBlacklist.buyer_id == body.buyer_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(BuyerBlacklist(owner_id=user.id, buyer_id=body.buyer_id, reason=body.reason))
        await session.commit()
    return {"buyer_id": body.buyer_id}


@router.delete("/orders-blacklist/{entry_id}", status_code=204)
async def remove_blacklist(entry_id: int, user: CurrentUser, session: SessionDep) -> None:
    row = await session.get(BuyerBlacklist, entry_id)
    if row and row.owner_id == user.id:
        await session.delete(row)
        await session.commit()


# ---------------------------------------------------------------- 买家分析（该不该卖给他）
class BuyerRiskIn(BaseModel):
    conv_id: int | None = None
    order_pk: int | None = None
    refresh: bool = False


async def _buyer_context(session, user, body: BuyerRiskIn) -> tuple[int, str, Conversation | None]:  # noqa: ANN001
    """按会话或订单定位买家：返回 (账号 ID, 买家 ID, 会话)。"""
    conv = None
    if body.conv_id is not None:
        conv = await session.get(Conversation, body.conv_id)
        if conv is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
        await get_account_for(session, user, conv.account_id)
        account_id, buyer_id = conv.account_id, conv.peer_id
    elif body.order_pk is not None:
        order = await _own_order(session, user, body.order_pk)
        account_id, buyer_id = order.account_id, order.buyer_id
        if buyer_id:
            conv = (
                await session.execute(
                    select(Conversation)
                    .where(Conversation.account_id == account_id, Conversation.peer_id == buyer_id)
                    .order_by(Conversation.last_message_at.desc().nulls_last())
                    .limit(1)
                )
            ).scalar_one_or_none()
    else:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "需要 conv_id 或 order_pk")
    if not buyer_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未获取到买家 ID")
    return account_id, buyer_id, conv


async def _shop_history(session, user, buyer_id: str) -> ShopHistory:  # noqa: ANN001
    stmt = select(Order.status, func.count(), func.coalesce(func.sum(Order.amount), 0)).where(
        Order.buyer_id == buyer_id
    )
    allowed = await accessible_account_ids(session, user)
    if allowed is not None:
        stmt = stmt.where(Order.account_id.in_(allowed))
    h = ShopHistory()
    for st, n, amount in await session.execute(stmt.group_by(Order.status)):
        h.orders += n
        if st == OrderState.COMPLETED:
            h.completed += n
            h.total_amount += float(amount or 0)
        elif st in (OrderState.REFUNDING, OrderState.REFUNDED):
            h.refunded += n
        elif st == OrderState.CLOSED:
            h.closed += n
    black = (
        await session.execute(
            select(BuyerBlacklist).where(BuyerBlacklist.owner_id == user.id, BuyerBlacklist.buyer_id == buyer_id)
        )
    ).scalar_one_or_none()
    if black is not None:
        h.blacklisted, h.blacklist_reason = True, black.reason
    return h


async def _chat(session, conv: Conversation | None) -> list[dict[str, Any]]:  # noqa: ANN001
    if conv is None:
        return []
    rows = await session.execute(
        select(ChatMessage)
        .where(ChatMessage.conversation_id == conv.id, ChatMessage.is_system.is_(False))
        .order_by(ChatMessage.id.desc())
        .limit(200)
    )
    return [{"direction": m.direction, "text": m.text or ""} for m in reversed(list(rows.scalars()))]


async def _analyze(session, user, body: BuyerRiskIn) -> tuple[BuyerAnalysis, list[dict[str, Any]]]:  # noqa: ANN001
    account_id, buyer_id, conv = await _buyer_context(session, user, body)
    profile, error = None, ""
    try:
        profile = await load_seller_profile(buyer_id, account_id, refresh=body.refresh)
    except GoofishError as e:  # 拉不到主页时仍基于聊天和本店记录给出结论
        error = str(e)[:120]
    chat = await _chat(session, conv)
    analysis = analyze_buyer(
        buyer_id,
        profile,
        messages=[m["text"] for m in chat if m["direction"] == "in" and m["text"]],
        bargain_rounds=conv.bargain_rounds if conv else 0,
        history=await _shop_history(session, user, buyer_id),
        profile_error=error,
    )
    if conv is not None and not analysis.nick:
        analysis.nick = conv.peer_name
    return analysis, chat


@router.post("/buyer-risk/analysis", response_model=BuyerAnalysis)
async def buyer_risk_analysis(body: BuyerRiskIn, user: CurrentUser, session: SessionDep) -> BuyerAnalysis:
    """规则分析：买家主页（缓存 24 小时）+ 当前聊天 + 本店交易记录。"""
    analysis, _ = await _analyze(session, user, body)
    return analysis


class BuyerInsightResp(BaseModel):
    analysis: BuyerAnalysis
    ai: BuyerInsightOut


@router.post("/buyer-risk/insight", response_model=BuyerInsightResp)
async def buyer_risk_insight(body: BuyerRiskIn, user: CurrentUser, session: SessionDep) -> BuyerInsightResp:
    analysis, chat = await _analyze(session, user, body)
    try:
        ai = await buyer_insight(get_llm(), analysis, chat)
    except LLMUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"大模型不可用：{e}") from e
    except LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return BuyerInsightResp(analysis=analysis, ai=ai)
