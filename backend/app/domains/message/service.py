"""消息中心：IM 事件入库、人工接管、合并连发消息、自动回复流水线、发送。"""

import asyncio
import random
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory
from app.core.events import Topics, bus
from app.core.realtime import hub
from app.domains.account.models import AccountSettings, XyAccount
from app.domains.goods.models import MyItem
from app.domains.message.agent import ReplyContext, compose_reply
from app.domains.message.models import ChatMessage, Conversation, MessageSource, ReplyRule, ReplySuggestion
from app.goofish.dto import ImEvent, ImEventType, SystemNotice
from app.intelligence.bargain import BargainAction, BargainState, decide
from app.intelligence.guardrails import detect_injection
from app.intelligence.intent import Intent, classify_intent
from app.intelligence.llm import get_llm
from app.notify.senders import Notification
from app.notify.service import NotifyEvents, notify
from app.workers.im_gateway import get_im_manager

_pending: dict[tuple[int, str], asyncio.Task] = {}
_tasks: set[asyncio.Task] = set()
_recent_sent: dict[tuple[int, str], list[tuple[str, float]]] = {}
ECHO_WINDOW = 120


def _spawn(coro) -> asyncio.Task:  # noqa: ANN001
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def drain() -> None:
    """等待所有挂起的回复任务（测试 / 优雅退出）。"""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)


def _aware(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def in_takeover(conv: Conversation) -> bool:
    until = _aware(conv.takeover_until)
    return bool(until and until > datetime.now(UTC))


def in_work_hours(settings: AccountSettings, now: datetime | None = None) -> bool:
    if not settings.work_hours:
        return True
    m = re.fullmatch(r"(\d{1,2}):(\d{2})-(\d{1,2}):(\d{2})", settings.work_hours.strip())
    if not m:
        return True
    now = now or datetime.now(UTC) + timedelta(hours=8)  # 北京时间
    start = int(m[1]) * 60 + int(m[2])
    end = int(m[3]) * 60 + int(m[4])
    cur = now.hour * 60 + now.minute
    return start <= cur < end if start <= end else (cur >= start or cur < end)


def _remember_sent(account_id: int, cid: str, text: str) -> None:
    now = time.time()
    bucket = [(t, ts) for t, ts in _recent_sent.get((account_id, cid), []) if now - ts < ECHO_WINDOW]
    bucket.append((text.strip(), now))
    _recent_sent[(account_id, cid)] = bucket


def _is_echo(account_id: int, cid: str, text: str) -> bool:
    now = time.time()
    bucket = _recent_sent.get((account_id, cid), [])
    for i, (t, ts) in enumerate(bucket):
        if t == text.strip() and now - ts < ECHO_WINDOW:
            bucket.pop(i)
            return True
    return False


# ---------------------------------------------------------------- 入库
async def _get_conversation(s: AsyncSession, account_id: int, cid: str) -> Conversation:
    conv = (
        await s.execute(select(Conversation).where(Conversation.account_id == account_id, Conversation.cid == cid))
    ).scalar_one_or_none()
    if conv is None:
        conv = Conversation(account_id=account_id, cid=cid)
        s.add(conv)
        await s.flush()
    return conv


async def save_message(
    s: AsyncSession,
    conv: Conversation,
    *,
    direction: str,
    source: str,
    text: str,
    sender_id: str | None = None,
    is_system: bool = False,
    notice: str | None = None,
    meta: dict[str, Any] | None = None,
) -> ChatMessage:
    msg = ChatMessage(
        conversation_id=conv.id,
        account_id=conv.account_id,
        direction=direction,
        source=source,
        sender_id=sender_id,
        text=text,
        is_system=is_system,
        notice=notice,
        meta=meta or {},
    )
    s.add(msg)
    conv.last_message = text[:200]
    conv.last_message_at = datetime.now(UTC)
    if direction == "in" and not is_system:
        conv.unread += 1
    return msg


async def handle_event(account_id: int, ev: ImEvent) -> None:
    if ev.type == ImEventType.ORDER:
        await bus.publish(
            Topics.ORDER_STATUS_CHANGED,
            {
                "account_id": account_id,
                "notice": ev.notice,
                "order_id": ev.order_id,
                "buyer_id": ev.sender_id,
                "status_text": ev.status_text,
                "item_id": ev.item_id,
                "cid": None,
            },
        )
        return
    if ev.type != ImEventType.CHAT or not ev.cid:
        return

    async with session_factory()() as s:
        acc = await s.get(XyAccount, account_id)
        if acc is None:
            return
        settings = acc.get_settings()
        conv = await _get_conversation(s, account_id, ev.cid)
        from_me = ev.sender_id == acc.unb
        if ev.item_id:
            conv.item_id = ev.item_id
        if not from_me and ev.sender_id:
            conv.peer_id = ev.sender_id
            conv.peer_name = ev.sender_name or conv.peer_name

        if ev.is_system:
            source = MessageSource.SYSTEM
        elif from_me:
            source = MessageSource.SELLER_APP
        else:
            source = MessageSource.BUYER
        echo = from_me and _is_echo(account_id, ev.cid, ev.text)
        if not echo:
            msg = await save_message(
                s,
                conv,
                direction="out" if from_me else "in",
                source=source,
                text=ev.text,
                sender_id=ev.sender_id,
                is_system=ev.is_system,
                notice=ev.notice if ev.notice != SystemNotice.NONE else None,
            )
        if from_me and not echo and not ev.is_system:
            # 卖家亲自回复 → 该会话进入人工接管
            conv.takeover_until = datetime.now(UTC) + timedelta(minutes=settings.takeover_minutes)
        await s.commit()
        conv_id = conv.id
        peer_id = conv.peer_id
        item_id = conv.item_id

    if not echo:
        await hub.publish(
            "message",
            {"conversation_id": conv_id, "account_id": account_id, "text": ev.text, "id": msg.id, "source": source},
            account_id=account_id,
        )

    if ev.is_system:
        if ev.notice != SystemNotice.NONE:
            await bus.publish(
                Topics.ORDER_STATUS_CHANGED,
                {
                    "account_id": account_id,
                    "notice": ev.notice,
                    "order_id": ev.order_id,
                    "buyer_id": peer_id,
                    "status_text": ev.text,
                    "item_id": item_id,
                    "cid": ev.cid,
                },
            )
        return
    if from_me:
        return

    await bus.publish(Topics.CHAT_MESSAGE_RECEIVED, {"account_id": account_id, "conversation_id": conv_id})
    _schedule_reply(account_id, ev.cid, conv_id, settings.merge_window_seconds)


def _schedule_reply(account_id: int, cid: str, conv_id: int, window: float) -> None:
    key = (account_id, cid)
    old = _pending.get(key)
    if old and not old.done():
        old.cancel()

    async def _later() -> None:
        try:
            if window > 0:
                await asyncio.sleep(window)
        except asyncio.CancelledError:
            return
        _pending.pop(key, None)
        try:
            await auto_reply(conv_id)
        except Exception:  # noqa: BLE001
            logger.exception("自动回复失败 conversation={}", conv_id)

    _pending[key] = _spawn(_later())


# ---------------------------------------------------------------- 自动回复
async def match_rule(
    s: AsyncSession, owner_id: int, account_id: int, item_id: str | None, text: str
) -> ReplyRule | None:
    rules = (
        await s.execute(
            select(ReplyRule).where(
                ReplyRule.owner_id == owner_id,
                ReplyRule.enabled.is_(True),
                or_(ReplyRule.account_id.is_(None), ReplyRule.account_id == account_id),
            )
        )
    ).scalars()
    best: tuple[tuple[int, int, int], ReplyRule] | None = None
    t = text.strip().lower()
    for rule in rules:
        if rule.item_id and rule.item_id != item_id:
            continue
        hit_len = 0
        for kw in rule.keywords:
            k = kw.strip().lower()
            if not k:
                continue
            if rule.match == "exact" and t == k:
                hit_len = max(hit_len, len(k))
            elif rule.match == "regex":
                try:
                    m = re.search(kw, text, re.IGNORECASE)
                except re.error:
                    m = None
                if m:
                    hit_len = max(hit_len, len(m.group(0)))
            elif rule.match == "contains" and k in t:
                hit_len = max(hit_len, len(k))
        if not hit_len:
            continue
        # 商品级 > 账号级 > 全局；同级按优先级、命中长度
        scope = 2 if rule.item_id else 1 if rule.account_id else 0
        rank = (scope, rule.priority, hit_len)
        if best is None or rank > best[0]:
            best = (rank, rule)
    return best[1] if best else None


async def _pending_buyer_text(s: AsyncSession, conv: Conversation) -> tuple[str, int]:
    """合并“上次处理之后、且在我方最后一次发言之后”买家发来的全部消息。返回 (文本, 最大消息 ID)。"""
    msgs = list(
        (
            await s.execute(
                select(ChatMessage)
                .where(
                    ChatMessage.conversation_id == conv.id,
                    ChatMessage.is_system.is_(False),
                    ChatMessage.id > (conv.handled_upto_id or 0),
                )
                .order_by(ChatMessage.id.desc())
                .limit(20)
            )
        ).scalars()
    )
    buf: list[str] = []
    max_id = conv.handled_upto_id or 0
    for m in msgs:
        max_id = max(max_id, m.id)
        if m.direction == "out":
            break
        buf.append(m.text)
    return "\n".join(reversed(buf)).strip(), max_id


async def _history(s: AsyncSession, conv_id: int) -> list[tuple[str, str]]:
    msgs = (
        await s.execute(
            select(ChatMessage)
            .where(ChatMessage.conversation_id == conv_id, ChatMessage.is_system.is_(False))
            .order_by(ChatMessage.id.desc())
            .limit(12)
        )
    ).scalars()
    return [("me" if m.direction == "out" else "buyer", m.text) for m in reversed(list(msgs))]


async def plan_reply(conv_id: int, *, dry_run_text: str | None = None) -> dict[str, Any]:
    """计算应当如何回复（不发送）。返回 {action, text, source, intent, note, ...}。"""
    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        if conv is None:
            return {"action": "none", "note": "会话不存在"}
        acc = await s.get(XyAccount, conv.account_id)
        assert acc is not None
        settings = acc.get_settings()
        if dry_run_text is not None:
            text = dry_run_text
        else:
            text, upto = await _pending_buyer_text(s, conv)
            conv.handled_upto_id = upto  # 无论最终是否回复，这些消息都视为已处理
            await s.commit()
        if not text:
            return {"action": "none", "note": "没有待回复的买家消息"}
        if dry_run_text is None and in_takeover(conv):
            return {"action": "none", "note": "人工接管中"}
        if detect_injection(text):
            return {"action": "none", "note": "疑似套取设定 / 探测，不回复", "intent": Intent.NO_REPLY}

        rule = await match_rule(s, acc.owner_id, acc.id, conv.item_id, text) if settings.keyword_reply else None
        if rule is not None and not (rule.reply_once and rule.hits and conv.tags and f"rule:{rule.id}" in conv.tags):
            return {"action": "send", "text": rule.reply, "source": MessageSource.AUTO_KEYWORD, "rule_id": rule.id}

        item = None
        if conv.item_id:
            item = (
                await s.execute(select(MyItem).where(MyItem.account_id == acc.id, MyItem.item_id == conv.item_id))
            ).scalar_one_or_none()
        history = await _history(s, conv_id)
        bargain_state = BargainState(conv.bargain_rounds, conv.bargain_last_offer)
        default_reply = settings.default_reply if not conv.default_replied else None

    llm = get_llm()
    if settings.ai_mode == "off" or not in_work_hours(settings):
        if default_reply:
            return {"action": "send", "text": default_reply, "source": MessageSource.AUTO_DEFAULT}
        return {"action": "none", "note": "AI 未开启或不在工作时段"}

    intent = await classify_intent(text, llm)
    if intent == Intent.NO_REPLY:
        return {"action": "none", "note": "无需回复", "intent": intent}
    if intent == Intent.AFTER_SALE:
        return {"action": "handoff", "note": "售后 / 纠纷，转人工", "intent": intent}

    decision = None
    policy = item.bargain_policy() if item else None
    if intent == Intent.BARGAIN and policy is not None:
        decision = decide(policy, bargain_state, text, want_cnt=item.want_cnt if item else None)

    ctx = ReplyContext(
        item_title=item.title if item else "",
        item_price=item.price if item else None,
        item_desc=item.desc if item else "",
        knowledge=item.knowledge if item else "",
        history=history,
        # 没有配置议价策略时，任何低于标价的报价都会被护栏拦截
        floor_price=(policy.floor_price if policy else (item.price if item else None)),
    )
    reply = await compose_reply(llm, ctx, intent, text, decision)
    plan: dict[str, Any] = {
        "intent": intent,
        "text": reply.text,
        "source": MessageSource.AUTO_AI,
        "note": reply.note,
        "violations": reply.violations,
        "need_human": reply.need_human,
        "used_llm": reply.used_llm,
    }
    if decision is not None:
        plan["bargain"] = {
            "action": decision.action,
            "offer": decision.offer,
            "rounds_after": decision.rounds_after,
            "is_final": decision.is_final,
        }
    if not reply.text:
        plan["action"] = "handoff" if reply.need_human else "none"
        return plan
    plan["action"] = "suggest" if settings.ai_mode == "suggest" else "send"
    return plan


async def auto_reply(conv_id: int) -> dict[str, Any]:
    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        if conv is None:
            return {}
        acc = await s.get(XyAccount, conv.account_id)
        settings = acc.get_settings()
        owner_id, nickname = acc.owner_id, acc.nickname or acc.unb
    if not settings.auto_reply and settings.ai_mode != "suggest":
        return {"action": "none", "note": "自动回复未开启"}

    plan = await plan_reply(conv_id)
    action = plan.get("action")
    if action == "send" and not settings.auto_reply:
        action = "suggest" if plan.get("source") == MessageSource.AUTO_AI else "none"

    if action == "handoff" or plan.get("need_human"):
        await set_takeover(conv_id, settings.takeover_minutes)
        await notify(
            owner_id,
            Notification(
                event=NotifyEvents.HUMAN_HANDOFF,
                title=f"💬 需要人工回复（{nickname}）",
                content=f"{plan.get('note', '')}\n买家：{conv.peer_name or conv.peer_id}\n最新消息：{conv.last_message}",
            ),
        )
    if action == "suggest" and plan.get("text"):
        async with session_factory()() as s:
            sug = ReplySuggestion(
                conversation_id=conv_id,
                text=plan["text"],
                intent=str(plan.get("intent", "")),
                note=plan.get("note", ""),
            )
            s.add(sug)
            await s.commit()
            await hub.publish(
                "suggestion", {"conversation_id": conv_id, "id": sug.id, "text": sug.text}, account_id=conv.account_id
            )
    elif action == "send" and plan.get("text"):
        delay = random.uniform(settings.reply_delay_min, max(settings.reply_delay_min, settings.reply_delay_max))
        if settings.reply_delay_max > 0:  # 模拟打字时间
            delay += min(len(plan["text"]) * 0.15, 6)
        await asyncio.sleep(delay)
        async with session_factory()() as s:  # 等待期间卖家可能已接管
            conv = await s.get(Conversation, conv_id)
            if conv is None or in_takeover(conv):
                return {"action": "none", "note": "等待期间进入人工接管"}
        await send_text(conv_id, plan["text"], source=plan["source"], meta={"intent": str(plan.get("intent", ""))})
        async with session_factory()() as s:
            conv = await s.get(Conversation, conv_id)
            if "bargain" in plan:
                b = plan["bargain"]
                conv.bargain_rounds = b["rounds_after"]
                if b["action"] != BargainAction.ACCEPT:
                    conv.bargain_last_offer = b["offer"]
            if plan["source"] == MessageSource.AUTO_DEFAULT:
                conv.default_replied = True
            if plan.get("rule_id"):
                rule = await s.get(ReplyRule, plan["rule_id"])
                if rule:
                    rule.hits += 1
                    conv.tags = [*(conv.tags or []), f"rule:{rule.id}"]
            await s.commit()
    plan["action"] = action
    return plan


# ---------------------------------------------------------------- 发送 / 接管
async def send_text(conv_id: int, text: str, *, source: str, meta: dict[str, Any] | None = None) -> ChatMessage:
    manager = get_im_manager()
    if manager is None:
        raise ConnectionError("IM 网关未运行")
    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        if conv is None or not conv.peer_id:
            raise ValueError("会话不存在或缺少买家信息")
        account_id, cid, peer_id = conv.account_id, conv.cid, conv.peer_id
    _remember_sent(account_id, cid, text)
    await manager.send_text(account_id, cid, peer_id, text)
    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        msg = await save_message(s, conv, direction="out", source=source, text=text, meta=meta)
        await s.commit()
    await hub.publish(
        "message",
        {"conversation_id": conv_id, "account_id": account_id, "text": text, "id": msg.id, "source": source},
        account_id=account_id,
    )
    return msg


async def set_takeover(conv_id: int, minutes: int) -> None:
    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        if conv is None:
            return
        conv.takeover_until = datetime.now(UTC) + timedelta(minutes=minutes) if minutes > 0 else None
        await s.commit()


async def find_conversation(
    account_id: int, *, cid: str | None = None, peer_id: str | None = None, item_id: str | None = None
) -> Conversation | None:
    async with session_factory()() as s:
        stmt = select(Conversation).where(Conversation.account_id == account_id)
        if cid:
            stmt = stmt.where(Conversation.cid == cid)
        else:
            if peer_id:
                stmt = stmt.where(Conversation.peer_id == peer_id)
            if item_id:
                stmt = stmt.where(Conversation.item_id == item_id)
        return (await s.execute(stmt.order_by(Conversation.last_message_at.desc()).limit(1))).scalar_one_or_none()
