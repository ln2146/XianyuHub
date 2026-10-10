from datetime import datetime
from typing import Any

import jwt
from fastapi import (
    APIRouter,
    File,
    Form,
    HTTPException,
    Query,
    Response,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from app.core.db import session_factory
from app.core.deps import CurrentUser, SessionDep
from app.core.pagination import set_total
from app.core.realtime import hub
from app.core.security import user_id_from_token
from app.core.uploads import TooLarge, read_limited
from app.domains.account.models import XyAccount
from app.domains.account.service import accessible_account_ids, get_account_for
from app.domains.goods.models import MyItem
from app.domains.message import service
from app.domains.message.evidence import build_evidence
from app.domains.message.knowledge import MAX_FILE_BYTES, UnsupportedFile, extract_text_async
from app.domains.message.models import (
    ChatMessage,
    Conversation,
    KnowledgeDoc,
    MessageSource,
    ReplyRule,
    ReplySuggestion,
)
from app.domains.order.models import (
    ORDER_STATE_LABELS,
    CardBinding,
    CardItem,
    CardPool,
    DeliveryRecord,
    Order,
    OrderState,
)
from app.domains.system.models import User
from app.goofish.errors import RiskBlockedError
from app.workers.im_gateway import im_status_snapshot

router = APIRouter(prefix="/messages", tags=["messages"])
ws_router = APIRouter()


class ConversationOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    cid: str
    peer_id: str | None
    peer_name: str
    item_id: str | None
    last_message: str
    last_message_at: datetime | None
    unread: int
    takeover_until: datetime | None
    bargain_rounds: int
    in_takeover: bool = False


class ItemBrief(BaseModel):
    id: int | None = None
    account_id: int
    item_id: str
    title: str
    price: float | None = None
    floor_price: float | None = None
    image_url: str = ""
    status: str = ""
    desc: str = ""
    knowledge: str = ""
    is_virtual: bool = False
    want_cnt: int | None = None
    browse_cnt: int | None = None
    max_rounds: int = 3
    binding_info: dict[str, Any] | None = None


class OrderBrief(BaseModel):
    id: int
    order_id: str
    item_id: str | None = None
    item_title: str
    amount: float | None = None
    status: str
    status_label: str
    paid_at: datetime | None = None
    delivered_at: datetime | None = None
    is_bargain: bool = False
    fail_reason: str | None = None
    delivery_preview: str | None = None


class QuickReplyItem(BaseModel):
    tag: str
    text: str


class ConversationContextOut(BaseModel):
    conversation_id: int
    account_id: int
    account_name: str
    peer_id: str | None = None
    peer_name: str
    bargain_rounds: int = 0
    in_takeover: bool = False
    item: ItemBrief | None = None
    orders: list[OrderBrief] = []
    quick_replies: list[QuickReplyItem] = []


def generate_quick_replies(
    item: MyItem | None,
    orders: list[Order],
    bargain_rounds: int,
) -> list[QuickReplyItem]:
    replies: list[QuickReplyItem] = []

    # 1. 待发货 / 订单状态话术
    has_paid_order = any(o.status in (OrderState.PAID, OrderState.DELIVERING) for o in orders)
    if has_paid_order:
        replies.append(QuickReplyItem(tag="确认发货", text="已收到您的订单，正在为您打包/下发发货内容，请稍候~"))
        replies.append(
            QuickReplyItem(tag="核对地址", text="亲，已核对您的收货信息，无误今天就给您安排发出，感谢支持！")
        )

    # 2. 商品及议价拉扯话术
    if item and item.price is not None:
        p = item.price
        f = item.floor_price

        replies.append(QuickReplyItem(tag="现货在售", text="在的亲，宝贝功能完好成色如实拍图，喜欢可以直接拍下哦~"))

        if f is not None and f < p:
            mid = round((p + f) / 2)
            replies.append(
                QuickReplyItem(
                    tag="折中诚意", text=f"看您诚心要，各退一步 {mid} 元包顺丰给您，今天就能发走，您看可以的话我改价~"
                )
            )
            replies.append(
                QuickReplyItem(
                    tag="坚守底价",
                    text=f"朋友，{f} 元真是我这边的底线成本价了，亏本出闲置，不能再少了，爽快拍下直接发~",
                )
            )
        elif f is not None:
            replies.append(
                QuickReplyItem(
                    tag="底价声明", text=f"您好，标价 {p} 元已经是最低实价，成色很好不议价啦，诚心要今天可发~"
                )
            )
        else:
            replies.append(
                QuickReplyItem(
                    tag="小刀试探", text="亲，小刀可以接受，大刀勿扰哈，诚心要的话您报个心理价，合适就给您出~"
                )
            )

        replies.append(
            QuickReplyItem(
                tag="催促促单", text="宝贝还有多位朋友在咨询，先拍先得哦！今天 17:00 前拍下可赶上今天第一批发出~"
            )
        )
    else:
        replies.append(QuickReplyItem(tag="礼貌在", text="在的亲，有什么想了解的随时问我~"))
        replies.append(QuickReplyItem(tag="包邮说明", text="爽快不墨迹直接拍的朋友包邮发出哦~"))

    return replies


class MessageOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    direction: str
    source: str
    text: str
    is_system: bool
    notice: str | None
    created_at: datetime


class SendIn(BaseModel):
    text: str = Field(min_length=1, max_length=1000)


class TakeoverIn(BaseModel):
    minutes: int = Field(ge=0, le=24 * 60)


class RuleIn(BaseModel):
    name: str = ""
    account_id: int | None = None
    item_id: str | None = None
    keywords: list[str] = Field(min_length=1)
    match: str = Field(default="contains", pattern="^(contains|exact|regex)$")
    reply: str = Field(min_length=1, max_length=1000)
    priority: int = 0
    reply_once: bool = False
    enabled: bool = True


class RuleOut(RuleIn):
    model_config = {"from_attributes": True}

    id: int
    hits: int


class TestReplyIn(BaseModel):
    conversation_id: int
    text: str = Field(min_length=1, max_length=500)


async def _own_conv(session, user, conv_id: int) -> Conversation:
    conv = await session.get(Conversation, conv_id)
    if conv is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "会话不存在")
    await get_account_for(session, user, conv.account_id)
    return conv


def _conv_out(c: Conversation) -> ConversationOut:
    out = ConversationOut.model_validate(c)
    out.in_takeover = service.in_takeover(c)
    return out


@router.get("/conversations", response_model=list[ConversationOut])
async def list_conversations(
    user: CurrentUser,
    session: SessionDep,
    response: Response,
    account_id: int | None = None,
    q: str | None = None,
    limit: int = Query(50, le=200),
    offset: int = 0,
) -> list[ConversationOut]:
    ids = await accessible_account_ids(session, user)
    stmt = select(Conversation).order_by(Conversation.last_message_at.desc())
    if ids is not None:
        stmt = stmt.where(Conversation.account_id.in_(ids))
    if account_id is not None:
        stmt = stmt.where(Conversation.account_id == account_id)
    if q:
        stmt = stmt.where(Conversation.peer_name.contains(q) | Conversation.last_message.contains(q))
    await set_total(response, session, stmt)
    return [_conv_out(c) for c in (await session.execute(stmt.limit(limit).offset(offset))).scalars()]


@router.get("/conversations/unread-count")
async def get_unread_count(
    user: CurrentUser,
    session: SessionDep,
    account_id: int | None = None,
) -> dict[str, int]:
    """获取当前用户可访问账号的未读消息总数。"""
    ids = await accessible_account_ids(session, user)
    stmt = select(func.coalesce(func.sum(Conversation.unread), 0))
    if ids is not None:
        stmt = stmt.where(Conversation.account_id.in_(ids))
    if account_id is not None:
        stmt = stmt.where(Conversation.account_id == account_id)
    total_unread = (await session.execute(stmt)).scalar() or 0
    return {"total": int(total_unread)}


@router.get("/conversations/{conv_id}/evidence")
async def conversation_evidence(conv_id: int, user: CurrentUser, session: SessionDep) -> dict[str, str]:
    """售后 / 纠纷举证材料：订单、发货记录与完整聊天记录（Markdown）。"""
    conv = await _own_conv(session, user, conv_id)
    markdown, filename = await build_evidence(session, conv)
    return {"markdown": markdown, "filename": filename}


@router.get("/conversations/{conv_id}/context", response_model=ConversationContextOut)
async def conversation_context(conv_id: int, user: CurrentUser, session: SessionDep) -> ConversationContextOut:
    """会话上下文侧边栏数据：关联商品（售价/底价/库存）、买家订单记录、智能促单话术。"""
    conv = await _own_conv(session, user, conv_id)

    account = await session.get(XyAccount, conv.account_id)
    account_name = (account.nickname or account.remark or account.unb) if account else f"账号 #{conv.account_id}"

    # 1. 查找此买家 / 会话相关的订单
    orders_stmt = (
        select(Order)
        .where(
            Order.account_id == conv.account_id,
            or_(Order.cid == conv.cid, Order.buyer_id == conv.peer_id) if conv.peer_id else Order.cid == conv.cid,
        )
        .order_by(Order.created_at.desc())
    )
    orders = list((await session.execute(orders_stmt)).scalars())

    order_briefs: list[OrderBrief] = []
    for o in orders[:5]:
        deliv = (
            await session.execute(
                select(DeliveryRecord)
                .where(DeliveryRecord.order_pk == o.id)
                .order_by(DeliveryRecord.id.desc())
                .limit(1)
            )
        ).scalar_one_or_none()
        order_briefs.append(
            OrderBrief(
                id=o.id,
                order_id=o.order_id,
                item_id=o.item_id,
                item_title=o.item_title,
                amount=o.amount,
                status=o.status,
                status_label=ORDER_STATE_LABELS.get(o.status, o.status),
                paid_at=o.paid_at,
                delivered_at=o.delivered_at,
                is_bargain=o.is_bargain,
                fail_reason=o.fail_reason,
                delivery_preview=deliv.preview if deliv else None,
            )
        )

    # 2. 查找关联商品
    item_id = conv.item_id or next((o.item_id for o in orders if o.item_id), None)
    item_brief: ItemBrief | None = None
    my_item: MyItem | None = None

    if item_id:
        my_item = (
            await session.execute(select(MyItem).where(MyItem.account_id == conv.account_id, MyItem.item_id == item_id))
        ).scalar_one_or_none()

        if my_item:
            binding = (
                await session.execute(
                    select(CardBinding)
                    .where(
                        CardBinding.item_id == item_id,
                        or_(CardBinding.account_id == conv.account_id, CardBinding.account_id.is_(None)),
                    )
                    .limit(1)
                )
            ).scalar_one_or_none()
            binding_info = None
            if binding:
                pool = await session.get(CardPool, binding.pool_id)
                if pool:
                    stock_count = 0
                    if pool.kind == "pool":
                        stock_count = (
                            await session.scalar(
                                select(func.count()).where(CardItem.pool_id == pool.id, CardItem.status == "available")
                            )
                            or 0
                        )
                    binding_info = {
                        "pool_id": pool.id,
                        "pool_name": pool.name,
                        "kind": pool.kind,
                        "available_stock": stock_count,
                        "low_stock_threshold": pool.low_stock_threshold,
                        "delay_seconds": binding.delay_seconds,
                    }

            item_brief = ItemBrief(
                id=my_item.id,
                account_id=my_item.account_id,
                item_id=my_item.item_id,
                title=my_item.title,
                price=my_item.price,
                floor_price=my_item.floor_price,
                image_url=my_item.image_url,
                status=my_item.status,
                desc=my_item.desc,
                knowledge=my_item.knowledge,
                is_virtual=my_item.is_virtual,
                want_cnt=my_item.want_cnt,
                browse_cnt=my_item.browse_cnt,
                max_rounds=my_item.max_rounds,
                binding_info=binding_info,
            )
        else:
            order_title = next((o.item_title for o in orders if o.item_id == item_id and o.item_title), "")
            item_brief = ItemBrief(
                account_id=conv.account_id,
                item_id=item_id,
                title=order_title or f"商品 #{item_id}",
            )

    quick_replies = generate_quick_replies(my_item, orders, conv.bargain_rounds)

    return ConversationContextOut(
        conversation_id=conv.id,
        account_id=conv.account_id,
        account_name=account_name,
        peer_id=conv.peer_id,
        peer_name=conv.peer_name or "买家",
        bargain_rounds=conv.bargain_rounds,
        in_takeover=service.in_takeover(conv),
        item=item_brief,
        orders=order_briefs,
        quick_replies=quick_replies,
    )


@router.get("/conversations/{conv_id}/messages", response_model=list[MessageOut])
async def list_messages(conv_id: int, user: CurrentUser, session: SessionDep, before_id: int | None = None) -> list:
    conv = await _own_conv(session, user, conv_id)
    stmt = select(ChatMessage).where(ChatMessage.conversation_id == conv.id)
    if before_id:
        stmt = stmt.where(ChatMessage.id < before_id)
    rows = list((await session.execute(stmt.order_by(ChatMessage.id.desc()).limit(100))).scalars())
    return list(reversed(rows))


@router.post("/conversations/{conv_id}/read", status_code=204)
async def mark_read(conv_id: int, user: CurrentUser, session: SessionDep) -> None:
    conv = await _own_conv(session, user, conv_id)
    conv.unread = 0
    await session.commit()


@router.post("/conversations/{conv_id}/send", response_model=MessageOut)
async def send(conv_id: int, body: SendIn, user: CurrentUser, session: SessionDep) -> ChatMessage:
    conv = await _own_conv(session, user, conv_id)
    from app.domains.account.models import XyAccount

    acc = await session.get(XyAccount, conv.account_id)
    try:
        msg = await service.send_text(conv.id, body.text, source=MessageSource.WEB_MANUAL, meta={"user_id": user.id})
    except RiskBlockedError as e:
        raise HTTPException(status.HTTP_423_LOCKED, f"发送受限：{e}") from e
    except (ConnectionError, ValueError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    conv.unread = 0
    await session.commit()
    await service.set_takeover(conv.id, acc.get_settings().takeover_minutes)
    return msg


@router.post("/conversations/{conv_id}/takeover", response_model=ConversationOut)
async def takeover(conv_id: int, body: TakeoverIn, user: CurrentUser, session: SessionDep) -> ConversationOut:
    conv = await _own_conv(session, user, conv_id)
    await service.set_takeover(conv.id, body.minutes)
    await session.refresh(conv)
    return _conv_out(conv)


@router.get("/conversations/{conv_id}/suggestions")
async def suggestions(conv_id: int, user: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    conv = await _own_conv(session, user, conv_id)
    rows = await session.execute(
        select(ReplySuggestion)
        .where(ReplySuggestion.conversation_id == conv.id, ReplySuggestion.status == "pending")
        .order_by(ReplySuggestion.id.desc())
        .limit(5)
    )
    return [
        {"id": r.id, "text": r.text, "intent": r.intent, "note": r.note, "created_at": r.created_at}
        for r in rows.scalars()
    ]


@router.post("/suggestions/{sug_id}/{action}")
async def handle_suggestion(sug_id: int, action: str, user: CurrentUser, session: SessionDep) -> dict[str, str]:
    sug = await session.get(ReplySuggestion, sug_id)
    if sug is None or action not in ("send", "discard"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "建议不存在")
    conv = await _own_conv(session, user, sug.conversation_id)
    if action == "send":
        try:
            await service.send_text(
                sug.conversation_id, sug.text, source=MessageSource.AUTO_AI, meta={"approved_by": user.id}
            )
            conv.unread = 0
        except (ConnectionError, ValueError, RiskBlockedError) as e:
            raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    sug.status = "sent" if action == "send" else "discarded"
    await session.commit()
    return {"status": sug.status}


@router.post("/test-reply")
async def test_reply(body: TestReplyIn, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """试运行：给定一条买家消息，返回系统将如何回复（不发送、不改变会话状态）。"""
    conv = await _own_conv(session, user, body.conversation_id)
    return await service.plan_reply(conv.id, dry_run_text=body.text)


class TrialIn(BaseModel):
    account_id: int
    text: str = Field(min_length=1, max_length=500)
    item_id: str | None = None


@router.post("/ai-trial")
async def ai_trial(body: TrialIn, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """「自动回复」页试运行：不需要已有会话，演示当前规则、店主说明和资料下会怎么回（不发送）。"""
    await get_account_for(session, user, body.account_id)
    return await service.trial_reply(body.account_id, body.text, body.item_id or None)


# ---------------------------------------------------------------- AI 资料
class DocOut(BaseModel):
    id: int
    account_id: int | None
    name: str
    chars: int
    preview: str
    enabled: bool
    created_at: datetime


def _doc_out(d: KnowledgeDoc) -> DocOut:
    return DocOut(
        id=d.id,
        account_id=d.account_id,
        name=d.name,
        chars=len(d.content or ""),
        preview=(d.content or "")[:120],
        enabled=d.enabled,
        created_at=d.created_at,
    )


async def _own_doc(session, user: User, doc_id: int) -> KnowledgeDoc:  # noqa: ANN001
    d = await session.get(KnowledgeDoc, doc_id)
    if d is None or d.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "资料不存在")
    return d


@router.get("/knowledge-docs", response_model=list[DocOut])
async def list_docs(user: CurrentUser, session: SessionDep) -> list[DocOut]:
    rows = await session.execute(
        select(KnowledgeDoc).where(KnowledgeDoc.owner_id == user.id).order_by(KnowledgeDoc.id.desc())
    )
    return [_doc_out(d) for d in rows.scalars()]


@router.post("/knowledge-docs", response_model=DocOut, status_code=201)
async def upload_doc(
    user: CurrentUser,
    session: SessionDep,
    file: UploadFile = File(...),
    account_id: int | None = Form(default=None),
) -> DocOut:
    """上传给 AI 参考的资料（txt / md / csv / pdf / docx，≤ 50MB），保存提取出的文字。"""
    if account_id is not None:
        await get_account_for(session, user, account_id)
    try:
        data = await read_limited(file, MAX_FILE_BYTES, "文件超过 50MB，请拆分后再上传")
        text = await extract_text_async(file.filename or "", data)
    except (UnsupportedFile, TooLarge) as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    d = KnowledgeDoc(owner_id=user.id, account_id=account_id, name=(file.filename or "资料")[:200], content=text)
    session.add(d)
    await session.commit()
    return _doc_out(d)


class DocPatch(BaseModel):
    enabled: bool | None = None
    account_id: int | None = None
    all_accounts: bool = False  # 改为所有账号通用（account_id 为空时区分“不修改”与“设为通用”）


@router.patch("/knowledge-docs/{doc_id}", response_model=DocOut)
async def update_doc(doc_id: int, body: DocPatch, user: CurrentUser, session: SessionDep) -> DocOut:
    d = await _own_doc(session, user, doc_id)
    if body.enabled is not None:
        d.enabled = body.enabled
    if body.all_accounts:
        d.account_id = None
    elif body.account_id is not None:
        await get_account_for(session, user, body.account_id)
        d.account_id = body.account_id
    await session.commit()
    return _doc_out(d)


@router.delete("/knowledge-docs/{doc_id}", status_code=204)
async def delete_doc(doc_id: int, user: CurrentUser, session: SessionDep) -> None:
    await session.delete(await _own_doc(session, user, doc_id))
    await session.commit()


# ---------------------------------------------------------------- 规则
@router.get("/rules", response_model=list[RuleOut])
async def list_rules(user: CurrentUser, session: SessionDep) -> list[ReplyRule]:
    rows = await session.execute(select(ReplyRule).where(ReplyRule.owner_id == user.id).order_by(ReplyRule.id))
    return list(rows.scalars())


@router.post("/rules", response_model=RuleOut, status_code=201)
async def create_rule(body: RuleIn, user: CurrentUser, session: SessionDep) -> ReplyRule:
    if body.account_id is not None:
        await get_account_for(session, user, body.account_id)
    rule = ReplyRule(owner_id=user.id, **body.model_dump())
    session.add(rule)
    await session.commit()
    return rule


@router.put("/rules/{rule_id}", response_model=RuleOut)
async def update_rule(rule_id: int, body: RuleIn, user: CurrentUser, session: SessionDep) -> ReplyRule:
    rule = await session.get(ReplyRule, rule_id)
    if rule is None or rule.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "规则不存在")
    for k, v in body.model_dump().items():
        setattr(rule, k, v)
    await session.commit()
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
async def delete_rule(rule_id: int, user: CurrentUser, session: SessionDep) -> None:
    rule = await session.get(ReplyRule, rule_id)
    if rule and rule.owner_id == user.id:
        await session.delete(rule)
        await session.commit()


@router.get("/im-status")
async def im_status(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    snapshot = await im_status_snapshot()
    ids = await accessible_account_ids(session, user)
    if snapshot is None:
        return {"running": False, "accounts": {}}
    return {
        "running": True,
        "accounts": {k: v for k, v in snapshot.items() if ids is None or int(k) in ids},
    }


# ---------------------------------------------------------------- WebSocket
@ws_router.websocket("/api/v1/ws")
async def realtime(ws: WebSocket, token: str = Query(...)) -> None:
    try:
        user_id = user_id_from_token(token)
    except jwt.PyJWTError:
        await ws.close(code=4401)
        return
    async with session_factory()() as s:
        user = await s.get(User, user_id)
        if user is None or not user.is_active:
            await ws.close(code=4401)
            return
        ids = await accessible_account_ids(s, user)
    await ws.accept()
    conn = await hub.add(ws, user.id, set(ids) if ids is not None else None)
    try:
        while True:
            await ws.receive_text()  # 客户端心跳
    except WebSocketDisconnect:
        pass
    finally:
        await hub.remove(conn)
