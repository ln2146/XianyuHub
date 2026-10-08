"""账号与会话中心：导入 / 扫码登录、探活续期、风控状态持久化与告警、访问控制。"""

import asyncio
import json
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import get_vault
from app.core.db import session_factory
from app.core.events import Topics, bus
from app.domains.account.models import AccountGrant, RiskEvent, XyAccount
from app.domains.account.store import DbSessionStore
from app.domains.system.audit import record_audit
from app.domains.system.models import Role, User
from app.goofish.errors import GoofishError, SessionExpiredError
from app.goofish.gateway import account_key
from app.goofish.guard.guard import AccountState, Runtime
from app.goofish.guard.policy import Action
from app.goofish.protocol.cookies import is_logged_in, parse_cookie_str
from app.goofish.protocol.login import QrLoginClient, QrSession, QrStatus, has_login_renew
from app.goofish.protocol.sign import gen_device_id
from app.notify.senders import Notification
from app.notify.service import NotifyEvents, notify
from app.runtime import get_runtime


def account_id_from_key(key: str) -> int | None:
    return int(key.split(":", 1)[1]) if key.startswith("acc:") else None


# ---------------------------------------------------------------- 访问控制
async def accessible_account_ids(session: AsyncSession, user: User) -> list[int] | None:
    """返回用户可访问的账号 ID；管理员返回 None 表示全部。"""
    if user.role == Role.ADMIN:
        return None
    rows = await session.execute(
        select(XyAccount.id).where(
            or_(
                XyAccount.owner_id == user.id,
                XyAccount.id.in_(select(AccountGrant.account_id).where(AccountGrant.user_id == user.id)),
            )
        )
    )
    return [r[0] for r in rows]


async def get_account_for(session: AsyncSession, user: User, account_id: int) -> XyAccount:
    acc = await session.get(XyAccount, account_id)
    if acc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    allowed = await accessible_account_ids(session, user)
    if allowed is not None and acc.id not in allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    return acc


# ---------------------------------------------------------------- 风控状态同步
def sync_runtime_to_model(acc: XyAccount, rt: Runtime) -> None:
    acc.status = rt.state
    acc.strikes = rt.strikes
    acc.health_score = rt.health
    acc.last_error = rt.last_error
    acc.punish_url = rt.punish_url
    acc.cooldown_until = datetime.fromtimestamp(rt.cooldown_until, UTC) if rt.cooldown_until else None


async def on_guard_state_change(key: str, rt: Runtime, reason: str) -> None:
    """RiskGuard 状态变化 → 落库、记录风控事件、发通知。"""
    account_id = account_id_from_key(key)
    owner_id = None
    nickname = key
    async with session_factory()() as s:
        if account_id is not None:
            acc = await s.get(XyAccount, account_id)
            if acc is not None:
                sync_runtime_to_model(acc, rt)
                owner_id, nickname = acc.owner_id, acc.nickname or acc.unb
        if rt.state in (AccountState.CIRCUIT_OPEN, AccountState.NEED_LOGIN):
            s.add(
                RiskEvent(account_id=account_id, guard_key=key, state=rt.state, reason=reason, punish_url=rt.punish_url)
            )
        await s.commit()

    await bus.publish(Topics.ACCOUNT_STATUS_CHANGED, {"account_id": account_id, "state": rt.state, "reason": reason})
    if rt.state == AccountState.CIRCUIT_OPEN:
        await bus.publish(Topics.ACCOUNT_RISK_DETECTED, {"account_id": account_id, "reason": reason})
        content = f"原因：{reason}\n已自动暂停该账号的写操作。请打开验证链接完成验证，然后在管理台点击「已处理」。"
        await notify(
            owner_id,
            Notification(
                event=NotifyEvents.ACCOUNT_RISK, title=f"⚠️ 账号 {nickname} 触发风控", content=content, url=rt.punish_url
            ),
        )
    elif rt.state == AccountState.NEED_LOGIN and account_id is not None:
        await notify(
            owner_id,
            Notification(
                event=NotifyEvents.ACCOUNT_LOGIN_REQUIRED,
                title=f"账号 {nickname} 登录已失效",
                content="自动续期失败，请在管理台重新扫码登录。",
            ),
        )


async def load_guard_states() -> None:
    rt = get_runtime()
    async with session_factory()() as s:
        for acc in (await s.execute(select(XyAccount))).scalars():
            cooldown = acc.cooldown_until.timestamp() if acc.cooldown_until else 0.0
            try:
                rt.guard.load(account_key(acc.id), acc.status, cooldown, acc.strikes)
            except ValueError:
                rt.guard.load(account_key(acc.id), AccountState.NEED_LOGIN)


# ---------------------------------------------------------------- 创建 / 导入
async def upsert_account(
    session: AsyncSession, owner: User, cookies: dict[str, str], proxy: str | None = None
) -> XyAccount:
    unb = cookies.get("unb")
    if not unb or not is_logged_in(cookies):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cookie 不完整：需要包含 unb、cookie2、_m_h5_tk")
    acc = (await session.execute(select(XyAccount).where(XyAccount.unb == unb))).scalar_one_or_none()
    if acc is None:
        acc = XyAccount(owner_id=owner.id, unb=unb, nickname=cookies.get("tracknick", ""), device_id=gen_device_id(unb))
        session.add(acc)
    elif acc.owner_id != owner.id and owner.role != Role.ADMIN:
        raise HTTPException(status.HTTP_409_CONFLICT, "该闲鱼账号已被其他用户添加")
    if proxy is not None:
        acc.proxy_enc = get_vault().encrypt(proxy) if proxy else None
    acc.status = AccountState.ACTIVE
    acc.last_error = None
    acc.punish_url = None
    await session.commit()
    await DbSessionStore().save_cookies(acc.id, cookies)
    rt = get_runtime()
    await rt.gateway.invalidate(acc.id)
    rt.guard.load(account_key(acc.id), AccountState.ACTIVE, 0, acc.strikes)
    await record_audit("account.login", user_id=owner.id, actor_type="human", account_id=acc.id, detail={"unb": unb})
    return acc


async def probe_account(account_id: int) -> bool:
    """探活：校验登录态；失效时尝试 hasLogin 续期。返回是否可用。"""
    rt = get_runtime()
    store = DbSessionStore()
    try:
        data = await rt.gateway.probe_login(account_id)
        async with session_factory()() as s:
            acc = await s.get(XyAccount, account_id)
            if acc is not None:
                acc.last_probe_at = datetime.now(UTC)
                nick = data.get("nick") or data.get("displayName") or data.get("userNick")
                if nick:
                    acc.nickname = nick
                sync_runtime_to_model(acc, rt.guard.runtime(account_key(account_id)))
                await s.commit()
        return True
    except SessionExpiredError:
        cookies = await store.load_cookies(account_id)
        try:
            renewed = await has_login_renew(cookies, proxy=await store.get_proxy(account_id))
        except Exception:  # noqa: BLE001
            renewed = False
        if renewed and is_logged_in(cookies):
            await store.save_cookies(account_id, cookies)
            await rt.gateway.invalidate(account_id)
            await rt.guard.set_state(account_key(account_id), AccountState.ACTIVE, "hasLogin 续期成功")
            logger.info("账号 {} 登录态续期成功", account_id)
            return True
        return False
    except GoofishError as e:
        logger.warning("账号 {} 探活失败：{}", account_id, e)
        return False


async def keepalive_all() -> None:
    """定时任务：对所有活跃账号探活（间隔由调度器控制）。"""
    async with session_factory()() as s:
        ids = [a for (a,) in await s.execute(select(XyAccount.id).where(XyAccount.status == AccountState.ACTIVE))]
    for account_id in ids:
        await probe_account(account_id)
        await asyncio.sleep(2)


async def resolve_risk(account_id: int, user: User) -> None:
    rt = get_runtime()
    await rt.guard.resolve(account_key(account_id))
    async with session_factory()() as s:
        events = await s.execute(
            select(RiskEvent).where(RiskEvent.account_id == account_id, RiskEvent.resolved_at.is_(None))
        )
        for ev in events.scalars():
            ev.resolved_at = datetime.now(UTC)
        await s.commit()
    await record_audit("account.risk_resolved", user_id=user.id, actor_type="human", account_id=account_id)


# ---------------------------------------------------------------- 扫码登录会话
@dataclass
class _QrEntry:
    owner_id: int
    proxy: str | None
    client: QrLoginClient
    session: QrSession
    created: float = field(default_factory=time.time)
    status: QrStatus = QrStatus.NEW
    account_id: int | None = None
    verify_url: str | None = None
    message: str = ""


class QrLoginManager:
    TTL = 300

    def __init__(self) -> None:
        self._entries: dict[str, _QrEntry] = {}

    async def _gc(self) -> None:
        now = time.time()
        for key in [k for k, e in self._entries.items() if now - e.created > self.TTL]:
            entry = self._entries.pop(key)
            await entry.client.aclose()

    async def start(self, owner: User, proxy: str | None = None) -> tuple[str, str]:
        await self._gc()
        client = QrLoginClient(proxy=proxy)
        sess = await get_runtime().guard.run("login", Action.LOGIN, client.start)
        qr_id = secrets.token_urlsafe(12)
        self._entries[qr_id] = _QrEntry(owner_id=owner.id, proxy=proxy, client=client, session=sess)
        return qr_id, sess.qr_content

    async def poll(self, qr_id: str, user: User) -> _QrEntry:
        entry = self._entries.get(qr_id)
        if entry is None or entry.owner_id != user.id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "二维码不存在或已过期")
        if entry.status in (QrStatus.SUCCESS, QrStatus.EXPIRED, QrStatus.CANCELED, QrStatus.ERROR):
            return entry
        result = await entry.client.poll(entry.session)
        entry.status, entry.verify_url, entry.message = result.status, result.verify_url, result.message
        if result.status == QrStatus.SUCCESS:
            async with session_factory()() as s:
                acc = await upsert_account(s, user, result.cookies, entry.proxy)
                entry.account_id = acc.id
            await entry.client.aclose()
        return entry


qr_manager = QrLoginManager()


def parse_cookie_input(raw: str) -> dict[str, str]:
    """支持 `a=1; b=2` 字符串，或浏览器扩展导出的 JSON（[{name,value}] / {cookies:[...]}）。"""
    raw = raw.strip()
    if raw.startswith("[") or raw.startswith("{"):
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Cookie JSON 格式错误") from e
        items = data.get("cookies", []) if isinstance(data, dict) else data
        return {c["name"]: c["value"] for c in items if isinstance(c, dict) and "name" in c and "value" in c}
    return parse_cookie_str(raw)
