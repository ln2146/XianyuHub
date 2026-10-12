"""消息中心：IM 事件入库、人工接管、合并连发消息、自动回复流水线、发送。"""

import asyncio
import random
import re
import time
from datetime import UTC, datetime, timedelta
from typing import Any

from loguru import logger
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory
from app.core.events import Topics, bus
from app.core.realtime import hub
from app.domains.account.models import AccountSettings, XyAccount
from app.domains.goods.models import MyItem
from app.domains.message.agent import ReplyContext, compose_reply
from app.domains.message.knowledge import select_from_docs
from app.domains.message.models import (
    ChatMessage,
    Conversation,
    KnowledgeDoc,
    MessageSource,
    ReplyRule,
    ReplySuggestion,
)
from app.domains.order.models import BuyerBlacklist, Order
from app.goofish.dto import ImEvent, ImEventType, SystemNotice
from app.goofish.errors import RiskBlockedError
from app.goofish.publish import UploadedImage
from app.intelligence.bargain import BargainAction, BargainPolicy, BargainState, decide
from app.intelligence.guardrails import detect_injection
from app.intelligence.intent import Intent, classify_intent, is_post_purchase_complaint
from app.intelligence.llm import get_llm
from app.intelligence.retrieval import select_knowledge
from app.notify.senders import Notification
from app.notify.service import NotifyEvents, notify, notify_background
from app.notify.service import drain as drain_notifications
from app.runtime import get_runtime
from app.workers.im_gateway import get_im_manager

_pending: dict[tuple[int, str], asyncio.Task] = {}
# 同一条消息（重连后服务端重推的帧）只处理一次：(账号, 会话, 发送者, 发送时间, 文本) → 收到时间
_seen_events: dict[tuple, float] = {}
SEEN_TTL = 600
# 发送时间早于这么久的消息只入库、不自动回复（断线重连后补推的历史消息，回复已经没有意义）
STALE_REPLY_SECONDS = 600
_tasks: set[asyncio.Task] = set()
_recent_sent: dict[tuple[int, str], list[tuple[str, float]]] = {}
ECHO_WINDOW = 120


def _spawn(coro) -> asyncio.Task:  # noqa: ANN001
    task = asyncio.create_task(coro)
    _tasks.add(task)
    task.add_done_callback(_tasks.discard)
    return task


async def drain() -> None:
    """等待所有挂起的回复任务及其后台通知（测试 / 优雅退出）。"""
    while _tasks:
        await asyncio.gather(*list(_tasks), return_exceptions=True)
    await drain_notifications()


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
                "event_at": ev.created_at.isoformat() if ev.created_at else None,
            },
        )
        return
    if ev.type != ImEventType.CHAT or not ev.cid:
        return
    if ev.created_at is not None:
        now = time.time()
        for k in [k for k, t in _seen_events.items() if now - t > SEEN_TTL]:
            _seen_events.pop(k, None)
        key = (account_id, ev.cid, ev.sender_id, ev.created_at.timestamp(), ev.text)
        if key in _seen_events:
            return  # 重复推送
        _seen_events[key] = now

    async with session_factory()() as s:
        acc = await s.get(XyAccount, account_id)
        if acc is None:
            return
        settings = acc.get_settings()
        conv = await _get_conversation(s, account_id, ev.cid)
        # 新会话还没有任何消息：用来判断「新买家第一次来咨询」
        first_contact = conv.last_message_at is None
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
                # 留存内容类型：平台调整消息形态时有据可查
                meta={"content_type": ev.content_type} if ev.content_type is not None else None,
            )
        if from_me and not echo and not ev.is_system:
            # 卖家亲自回复 → 该会话进入人工接管
            conv.takeover_until = datetime.now(UTC) + timedelta(minutes=settings.takeover_minutes)
        await s.commit()
        conv_id = conv.id
        peer_id = conv.peer_id
        item_id = conv.item_id
        owner_id, nickname = acc.owner_id, acc.nickname or acc.unb
        peer_name = conv.peer_name or conv.peer_id

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
                    "event_at": ev.created_at.isoformat() if ev.created_at else None,
                },
            )
        return
    if from_me:
        return

    await bus.publish(Topics.CHAT_MESSAGE_RECEIVED, {"account_id": account_id, "conversation_id": conv_id})
    if first_contact:
        notify_background(
            owner_id,
            Notification(
                event=NotifyEvents.NEW_MESSAGE,
                title=f"💬 新买家咨询（{nickname}）",
                content=f"买家：{peer_name}\n消息：{ev.text[:200]}",
            ),
        )
    if ev.created_at is not None and time.time() - ev.created_at.timestamp() > STALE_REPLY_SECONDS:
        logger.info("跳过过期消息的自动回复 conversation={} sent_at={}", conv_id, ev.created_at)
        return
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
        except Exception as e:  # noqa: BLE001
            logger.exception("自动回复失败 conversation={}", conv_id)
            # 这些买家消息已记为处理过，不提醒的话就再也没人回了
            await _alert_unanswered(conv_id, f"自动回复没有发出去（{e or type(e).__name__}），请人工回复")

    _pending[key] = _spawn(_later())


async def _alert_unanswered(conv_id: int, reason: str) -> None:
    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        acc = await s.get(XyAccount, conv.account_id) if conv else None
        if conv is None or acc is None:
            return
        owner_id, nickname = acc.owner_id, acc.nickname or acc.unb
        buyer, last = conv.peer_name or conv.peer_id, conv.last_message
    notify_background(
        owner_id,
        Notification(
            event=NotifyEvents.HUMAN_HANDOFF,
            title=f"💬 需要人工回复（{nickname}）",
            content=f"{reason}\n买家：{buyer}\n最新消息：{last}",
        ),
        dedupe_key=f"unanswered:{conv_id}",
    )


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


def _rule_plan(rule: ReplyRule) -> dict[str, Any]:
    if rule.action == "handoff":
        plan: dict[str, Any] = {
            "action": "send" if rule.reply.strip() else "handoff",
            "need_human": True,
            "note": f"命中转人工规则「{rule.name or '、'.join(rule.keywords)}」",
        }
        if rule.reply.strip():
            plan["text"] = rule.reply
    else:
        plan = {"action": "send", "text": rule.reply, "images": list(rule.images or [])}
    return {**plan, "source": MessageSource.AUTO_KEYWORD, "rule_id": rule.id}


async def _is_blacklisted(s: AsyncSession, owner_id: int, buyer_id: str | None) -> bool:
    if not buyer_id:
        return False
    found = await s.execute(
        select(BuyerBlacklist.id).where(BuyerBlacklist.owner_id == owner_id, BuyerBlacklist.buyer_id == buyer_id)
    )
    return found.first() is not None


async def _has_ordered(s: AsyncSession, conv: Conversation) -> bool:
    """买家在这个账号下过单（任何状态），或会话里出现过付款 / 发货等订单通知：之后说「退款」「有问题」才可能是售后纠纷。"""
    if conv.peer_id:
        found = await s.execute(
            select(Order.id).where(Order.account_id == conv.account_id, Order.buyer_id == conv.peer_id).limit(1)
        )
        if found.first() is not None:
            return True
    notice = await s.execute(
        select(ChatMessage.id).where(ChatMessage.conversation_id == conv.id, ChatMessage.notice.is_not(None)).limit(1)
    )
    return notice.first() is not None


def _bargain_policy(item: MyItem | None, settings: AccountSettings) -> BargainPolicy | None:
    """商品自己设了底价就用商品的；否则按账号的默认议价范围（最多让百分之几 / 多少元）。"""
    if item is None:
        return None
    policy = item.bargain_policy()
    if policy is not None or not settings.bargain_default or not item.price:
        return policy
    discount = item.price * settings.bargain_max_percent / 100
    if settings.bargain_max_amount is not None:
        discount = min(discount, settings.bargain_max_amount)
    round_to = 1.0 if item.price >= 20 else 0.1
    floor = round(item.price - discount, 2)
    if discount < round_to or floor <= 0:
        return None
    return BargainPolicy(
        list_price=item.price,
        floor_price=floor,
        max_rounds=settings.bargain_max_rounds,
        gifts=item.gifts or "",
        round_to=round_to,
    )


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
        if await _is_blacklisted(s, acc.owner_id, conv.peer_id):
            return {"action": "none", "note": "黑名单买家，不自动回复"}
        if detect_injection(text):
            return {"action": "none", "note": "疑似套取设定 / 探测，不回复", "intent": Intent.NO_REPLY}

        rule = await match_rule(s, acc.owner_id, acc.id, conv.item_id, text) if settings.keyword_reply else None
        if rule is not None and not (rule.reply_once and rule.hits and conv.tags and f"rule:{rule.id}" in conv.tags):
            return _rule_plan(rule)

        item = None
        if conv.item_id:
            item = (
                await s.execute(select(MyItem).where(MyItem.account_id == acc.id, MyItem.item_id == conv.item_id))
            ).scalar_one_or_none()
        history = await _history(s, conv_id)
        bargain_state = BargainState(conv.bargain_rounds, conv.bargain_last_offer)
        default_reply = settings.default_reply if not conv.default_replied else None
        ordered = await _has_ordered(s, conv)

    if settings.ai_mode == "off" or not in_work_hours(settings):
        if default_reply:
            return {"action": "send", "text": default_reply, "source": MessageSource.AUTO_DEFAULT}
        return {"action": "none", "note": "AI 未开启或不在工作时段"}
    plan = await _ai_plan(acc.owner_id, acc.id, settings, item, history, bargain_state, text, ordered=ordered)
    if plan.get("text"):
        plan["action"] = "suggest" if settings.ai_mode == "suggest" else "send"
    return plan


async def _load_docs(owner_id: int, account_id: int, item_id: str | None = None) -> list[tuple[str, str]]:
    """账号可用的资料：通用 + 本账号；商品专属资料只在咨询的正是这件商品时带上，避免串款。"""
    item_cond = KnowledgeDoc.item_id.is_(None)
    if item_id:
        item_cond = or_(item_cond, KnowledgeDoc.item_id == item_id)
    async with session_factory()() as s:
        rows = await s.execute(
            select(KnowledgeDoc.name, KnowledgeDoc.content).where(
                KnowledgeDoc.owner_id == owner_id,
                KnowledgeDoc.enabled.is_(True),
                or_(KnowledgeDoc.account_id.is_(None), KnowledgeDoc.account_id == account_id),
                item_cond,
            )
        )
        return [(name, content) for name, content in rows]


async def _ai_plan(
    owner_id: int,
    account_id: int,
    settings: AccountSettings,
    item: MyItem | None,
    history: list[tuple[str, str]],
    bargain_state: BargainState,
    text: str,
    *,
    ordered: bool,
) -> dict[str, Any]:
    """AI 回复：意图 → 议价决策 → 结合商品、知识库、店主说明与资料写回复 → 护栏。不决定是否发送。
    ordered：买家是否在这个账号下过单。没下过单时，「退款」「售后」「有问题」都是售前咨询，交给 AI 正常回答。"""
    llm = get_llm()
    intent = await classify_intent(text, llm)
    if intent == Intent.NO_REPLY:
        return {"action": "none", "note": "无需回复", "intent": intent}
    if intent == Intent.AFTER_SALE and (ordered or is_post_purchase_complaint(text)):
        return {"action": "handoff", "note": "售后 / 纠纷，转人工", "intent": intent}

    decision = None
    policy = _bargain_policy(item, settings)
    if intent == Intent.BARGAIN and policy is not None:
        decision = decide(policy, bargain_state, text, want_cnt=item.want_cnt if item else None)

    ctx = ReplyContext(
        item_title=item.title if item else "",
        item_price=item.price if item else None,
        item_desc=item.desc if item else "",
        knowledge=select_knowledge(item.knowledge, text) if item else "",
        history=history,
        # 没有配置议价策略时，任何低于标价的报价都会被护栏拦截
        floor_price=(policy.floor_price if policy else (item.price if item else None)),
        instructions=settings.ai_instructions,
        docs=select_from_docs(await _load_docs(owner_id, account_id, item.item_id if item else None), text),
        ordered=ordered,
        banned_words=tuple(w.strip() for w in settings.ai_banned_words if w.strip()),
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
        "used_docs": bool(ctx.docs),
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


async def trial_reply(account_id: int, text: str, item_id: str | None = None) -> dict[str, Any]:
    """「自动回复」页的试运行：不需要已有会话，按当前规则、店主说明和资料演示会怎么回（不发送）。
    AI 未开启时也会给出 AI 的回答，方便开启前先看效果。"""
    async with session_factory()() as s:
        acc = await s.get(XyAccount, account_id)
        if acc is None:
            return {"action": "none", "note": "账号不存在"}
        settings = acc.get_settings()
        if detect_injection(text):
            return {"action": "none", "note": "疑似套取设定 / 探测，不回复", "intent": Intent.NO_REPLY}
        rule = await match_rule(s, acc.owner_id, acc.id, item_id, text) if settings.keyword_reply else None
        if rule is not None:
            return _rule_plan(rule)
        item = None
        if item_id:
            item = (
                await s.execute(select(MyItem).where(MyItem.account_id == acc.id, MyItem.item_id == item_id))
            ).scalar_one_or_none()
        owner_id = acc.owner_id
    # 试运行没有真实买家，按售前咨询处理
    plan = await _ai_plan(owner_id, account_id, settings, item, [], BargainState(0, None), text, ordered=False)
    if plan.get("text"):
        plan["action"] = {"off": "off", "suggest": "suggest"}.get(settings.ai_mode, "send")
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
        # 关闭期间的消息也记为已处理：否则重新打开后，下一条消息会把积压的旧消息一起合并回复
        async with session_factory()() as s:
            conv = await s.get(Conversation, conv_id)
            latest = (
                await s.execute(select(func.max(ChatMessage.id)).where(ChatMessage.conversation_id == conv_id))
            ).scalar_one_or_none()
            if conv is not None and latest:
                conv.handled_upto_id = max(conv.handled_upto_id or 0, latest)
                await s.commit()
        return {"action": "none", "note": "自动回复未开启"}

    plan = await plan_reply(conv_id)
    if plan.get("note") == "人工接管中":
        # 接管期间的买家消息不会自动回复：提醒正在接管的人去看（同一会话 10 分钟内只提醒一次）
        await _alert_unanswered(conv_id, "人工接管中，买家发来了新消息")
        return plan
    action = plan.get("action")
    if action == "send" and not settings.auto_reply:
        action = "suggest" if plan.get("source") == MessageSource.AUTO_AI else "none"

    handing_off = action == "handoff" or bool(plan.get("need_human"))
    if handing_off:
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
    elif action == "send" and (plan.get("text") or plan.get("images")):
        delay = random.uniform(settings.reply_delay_min, max(settings.reply_delay_min, settings.reply_delay_max))
        if settings.reply_delay_max > 0:  # 模拟打字时间
            delay += min(len(plan.get("text") or "") * 0.15, 6)
        await asyncio.sleep(delay)
        async with session_factory()() as s:  # 等待期间卖家可能已接管
            conv = await s.get(Conversation, conv_id)
            # 转人工时的过渡回复（如「我确认一下再回你」）要照常发出：接管是我们自己刚设的
            if conv is None or (in_takeover(conv) and not handing_off):
                return {"action": "none", "note": "等待期间进入人工接管"}
        if plan.get("text"):
            await send_text(conv_id, plan["text"], source=plan["source"], meta={"intent": str(plan.get("intent", ""))})
        if plan.get("images"):
            try:
                await send_images(conv_id, plan["images"], source=plan["source"])
            except Exception as e:  # noqa: BLE001  图片发不出去不影响文字回复，记下来让卖家知道
                logger.warning("自动回复的图片发送失败 conv={}: {}", conv_id, e)
                await _alert_unanswered(conv_id, f"自动回复的图片没有发出去：{e}")
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
    elif action == "handoff" and plan.get("rule_id"):
        async with session_factory()() as s:
            rule = await s.get(ReplyRule, plan["rule_id"])
            if rule:
                rule.hits += 1
                await s.commit()
    plan["action"] = action
    return plan


# ---------------------------------------------------------------- 发送 / 接管
async def im_send_local(account_id: int, cid: str, peer_id: str, text: str) -> None:
    """在持有 IM 长连接的进程内发送（同时登记回声，避免把自己发的消息当成卖家亲自回复）。"""
    manager = get_im_manager()
    if manager is None:
        raise ConnectionError("IM 网关未运行")
    _remember_sent(account_id, cid, text)
    await manager.send_text(account_id, cid, peer_id, text)


async def rpc_im_send(payload: dict[str, Any]) -> bool:
    await im_send_local(payload["account_id"], payload["cid"], payload["peer_id"], payload["text"])
    return True


async def im_send(account_id: int, cid: str, peer_id: str, text: str) -> None:
    if get_im_manager() is not None:
        await im_send_local(account_id, cid, peer_id, text)
        return
    from app.core.cluster import ClusterUnavailable, get_cluster

    cluster = get_cluster()
    if cluster is None:
        raise ConnectionError("IM 网关未运行")
    try:
        await cluster.call("im.send", {"account_id": account_id, "cid": cid, "peer_id": peer_id, "text": text})
    except (ClusterUnavailable, RuntimeError) as e:
        raise ConnectionError(str(e)) from e


IMAGE_ECHO = "[图片]"  # 图片消息回传时的提醒文案，用来识别自己发出的图片
_remote_images: dict[tuple[int, str], UploadedImage] = {}


async def im_send_image_local(account_id: int, cid: str, peer_id: str, image: dict[str, Any]) -> None:
    manager = get_im_manager()
    if manager is None:
        raise ConnectionError("IM 网关未运行")
    _remember_sent(account_id, cid, IMAGE_ECHO)
    await manager.send_image(account_id, cid, peer_id, image["url"], image["width"], image["height"])


async def rpc_im_send_image(payload: dict[str, Any]) -> bool:
    await im_send_image_local(payload["account_id"], payload["cid"], payload["peer_id"], payload["image"])
    return True


async def _remote_image(account_id: int, image_id: str) -> UploadedImage:
    """本地图片先传到闲鱼图床（每个账号传一次，结果缓存），聊天里只能发闲鱼图床的地址。"""
    key = (account_id, image_id)
    if key not in _remote_images:
        from app.domains.goods.service import load_upload

        try:
            content, _ = load_upload(image_id)
        except FileNotFoundError as e:
            raise ValueError("图片文件不存在，请重新上传") from e
        _remote_images[key] = await get_runtime().gateway.upload_image(account_id, content, image_id)
    return _remote_images[key]


async def send_images(conv_id: int, image_ids: list[str], *, source: str, meta: dict[str, Any] | None = None) -> int:
    """按顺序把图片发给买家，返回发出的张数。"""
    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        if conv is None or not conv.peer_id:
            raise ValueError("会话不存在或缺少买家信息")
        account_id, cid, peer_id = conv.account_id, conv.cid, conv.peer_id
    sent = 0
    for image_id in image_ids:
        img = await _remote_image(account_id, image_id)
        image = {"url": img.url, "width": img.width, "height": img.height}
        if get_im_manager() is not None:
            await im_send_image_local(account_id, cid, peer_id, image)
        else:
            from app.core.cluster import ClusterUnavailable, get_cluster

            cluster = get_cluster()
            if cluster is None:
                raise ConnectionError("IM 网关未运行")
            try:
                await cluster.call(
                    "im.send_image", {"account_id": account_id, "cid": cid, "peer_id": peer_id, "image": image}
                )
            except (ClusterUnavailable, RuntimeError) as e:
                raise ConnectionError(str(e)) from e
        sent += 1
        async with session_factory()() as s:
            conv = await s.get(Conversation, conv_id)
            msg = await save_message(
                s, conv, direction="out", source=source, text=IMAGE_ECHO, meta={**(meta or {}), "image": img.url}
            )
            await s.commit()
        await hub.publish(
            "message",
            {"conversation_id": conv_id, "account_id": account_id, "text": IMAGE_ECHO, "id": msg.id, "source": source},
            account_id=account_id,
        )
    return sent


# ---------------------------------------------------------------- 出口风控与敏感词过滤
_SENSITIVE_PATTERNS = [
    # 手机号 (11位数字，允许 +86，空格，破折号)
    (re.compile(r"(?:(?:\+?86[- ]?)?1[3-9]\d{9})|(?:1[3-9]\d{1}[- ]\d{4}[- ]\d{4})"), "疑似手机号码"),
    # 典型微信/QQ/站外交易导流关键字
    (
        re.compile(
            r"(?:加[微vV]|[vV微]\s*信|[vV][xX]|微\s*x|vx\s*号|v\s*号|加我[vV微]|私[聊信]|线下交易|加企鹅|[qQ][qQ]\s*号|走淘宝|走拼多多|走京东)",
            re.IGNORECASE,
        ),
        "站外导流敏感词（微信/QQ/站外交易）",
    ),
    # 变体引导：例如 "V: abc1234" 或 "微信：xxx"
    (
        re.compile(r"(?:[vV]|微信|vx)\s*[:：]\s*[a-zA-Z0-9_-]{5,25}", re.IGNORECASE),
        "微信号码/联系方式导流",
    ),
]


def check_sensitive_content(text: str) -> tuple[bool, str]:
    """检测外发消息中是否包含可能导致闲鱼封号的风控敏感词/联系方式。返回 (is_sensitive, reason)"""
    if not text:
        return False, ""
    for pattern, reason in _SENSITIVE_PATTERNS:
        if pattern.search(text):
            return True, reason
    return False, ""


async def send_text(conv_id: int, text: str, *, source: str, meta: dict[str, Any] | None = None) -> ChatMessage:
    is_sensitive, reason = check_sensitive_content(text)
    if is_sensitive:
        # 如果是自动化回复（AI、关键词、默认回复）：拦截外发，转人工接管并发布系统提示
        if source in (MessageSource.AUTO_AI, MessageSource.AUTO_KEYWORD, MessageSource.AUTO_DEFAULT):
            logger.warning("拦截自动化外发敏感消息 conv={}: reason={} text={}", conv_id, reason, text[:100])
            async with session_factory()() as s:
                conv = await s.get(Conversation, conv_id)
                if conv:
                    account_id = conv.account_id
                    conv.takeover_until = datetime.now(UTC) + timedelta(minutes=120)
                    intercept_msg = (
                        f"🛡️ [风控拦截] 系统拦截了拟自动发送的内容（{reason}），已暂停自动回复并转交人工：\n「{text}」"
                    )
                    msg = await save_message(
                        s,
                        conv,
                        direction="out",
                        source=MessageSource.SYSTEM,
                        text=intercept_msg,
                        meta={"intercepted": True, "original_source": source, "reason": reason},
                    )
                    await s.commit()
                    await hub.publish(
                        "message",
                        {
                            "conversation_id": conv_id,
                            "account_id": account_id,
                            "text": intercept_msg,
                            "id": msg.id,
                            "source": MessageSource.SYSTEM,
                        },
                        account_id=account_id,
                    )
            # 没有发给买家：调用方不能把它当成已发送（规则命中、建议「已发送」等）
            raise RiskBlockedError(f"敏感词拦截：{reason}，已转人工", state="sensitive_blocked")
        elif source == MessageSource.WEB_MANUAL:
            if not (meta and meta.get("force")):
                raise RiskBlockedError(
                    f"消息触发闲鱼导流风控（{reason}），请修改话术以防封号", state="sensitive_blocked"
                )

    async with session_factory()() as s:
        conv = await s.get(Conversation, conv_id)
        if conv is None or not conv.peer_id:
            raise ValueError("会话不存在或缺少买家信息")
        account_id, cid, peer_id = conv.account_id, conv.cid, conv.peer_id
    await im_send(account_id, cid, peer_id, text)
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
