from datetime import datetime
from typing import Any

import jwt
from fastapi import APIRouter, HTTPException, Query, Response, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.db import session_factory
from app.core.deps import CurrentUser, SessionDep
from app.core.pagination import set_total
from app.core.realtime import hub
from app.core.security import decode_access_token
from app.domains.account.service import accessible_account_ids, get_account_for
from app.domains.message import service
from app.domains.message.evidence import build_evidence
from app.domains.message.models import ChatMessage, Conversation, MessageSource, ReplyRule, ReplySuggestion
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


@router.get("/conversations/{conv_id}/evidence")
async def conversation_evidence(conv_id: int, user: CurrentUser, session: SessionDep) -> dict[str, str]:
    """售后 / 纠纷举证材料：订单、发货记录与完整聊天记录（Markdown）。"""
    conv = await _own_conv(session, user, conv_id)
    markdown, filename = await build_evidence(session, conv)
    return {"markdown": markdown, "filename": filename}


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
    await _own_conv(session, user, sug.conversation_id)
    if action == "send":
        try:
            await service.send_text(
                sug.conversation_id, sug.text, source=MessageSource.AUTO_AI, meta={"approved_by": user.id}
            )
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
        payload = decode_access_token(token)
    except jwt.PyJWTError:
        await ws.close(code=4401)
        return
    async with session_factory()() as s:
        user = await s.get(User, int(payload["sub"]))
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
