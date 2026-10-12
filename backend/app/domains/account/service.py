"""账号与会话中心：导入 / 扫码登录、探活续期、风控状态持久化与告警、访问控制。"""

import asyncio
import json
import math
import secrets
import time
from dataclasses import dataclass, field
from datetime import UTC, datetime
from urllib.parse import unquote

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.crypto import get_vault
from app.core.db import session_factory
from app.core.events import Topics, bus
from app.core.realtime import hub
from app.domains.account.models import AccountGrant, RiskEvent, XyAccount
from app.domains.account.store import DbSessionStore
from app.domains.system.audit import record_audit
from app.domains.system.models import Role, User
from app.goofish.errors import GoofishError, RiskBlockedError, SessionExpiredError
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
        elif rt.state == AccountState.ACTIVE and account_id is not None:
            unresolved = await s.execute(
                select(RiskEvent).where(RiskEvent.account_id == account_id, RiskEvent.resolved_at.is_(None))
            )
            now = datetime.now(UTC)
            for ev in unresolved.scalars():
                ev.resolved_at = now
        await s.commit()

    await bus.publish(Topics.ACCOUNT_STATUS_CHANGED, {"account_id": account_id, "state": rt.state, "reason": reason})
    await hub.publish("account", {"account_id": account_id, "state": rt.state, "reason": reason}, account_id=account_id)
    if rt.state == AccountState.CIRCUIT_OPEN:
        await bus.publish(Topics.ACCOUNT_RISK_DETECTED, {"account_id": account_id, "reason": reason})
        content = f"原因：{reason}\n已自动暂停该账号的写操作。请打开验证链接完成验证，然后在管理台点击「已处理」。"
        await notify(
            owner_id,
            Notification(
                event=NotifyEvents.ACCOUNT_RISK, title=f"⚠️ 账号 {nickname} 触发风控", content=content, url=rt.punish_url
            ),
            dedupe_key=f"account_risk:{key}",
        )
    elif rt.state == AccountState.NEED_LOGIN and account_id is not None:
        await notify(
            owner_id,
            Notification(
                event=NotifyEvents.ACCOUNT_LOGIN_REQUIRED,
                title=f"账号 {nickname} 登录已失效",
                content="自动续期失败，请在管理台重新扫码登录。",
            ),
            dedupe_key=f"account_login:{account_id}",
        )


async def reload_guard_state(account_id: int) -> None:
    """从数据库刷新单个账号的风控状态（其他进程修改后调用）。"""
    rt = get_runtime()
    async with session_factory()() as s:
        acc = await s.get(XyAccount, account_id)
        if acc is None:
            return
        cooldown = acc.cooldown_until.timestamp() if acc.cooldown_until else 0.0
        state, strikes, error, punish = acc.status, acc.strikes, acc.last_error, acc.punish_url
    key = account_key(account_id)
    try:
        rt.guard.load(key, state, cooldown, strikes)
    except ValueError:
        return
    runtime = rt.guard.runtime(key)
    runtime.last_error, runtime.punish_url = error, punish
    await rt.gateway.invalidate(account_id)


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
    raw_nick = cookies.get("tracknick", "")
    nick = unquote(raw_nick).strip() if raw_nick else ""
    acc = (await session.execute(select(XyAccount).where(XyAccount.unb == unb))).scalar_one_or_none()
    if acc is None:
        acc = XyAccount(owner_id=owner.id, unb=unb, nickname=nick, device_id=gen_device_id(unb))
        session.add(acc)
    elif acc.owner_id != owner.id and owner.role != Role.ADMIN:
        raise HTTPException(status.HTTP_409_CONFLICT, "该闲鱼账号已被其他用户添加")
    elif not acc.nickname and nick:
        acc.nickname = nick
    if proxy is not None:
        acc.proxy_enc = get_vault().encrypt(proxy) if proxy else None
    acc.status = AccountState.ACTIVE
    acc.last_error = None
    acc.punish_url = None
    await session.commit()
    # 重新登录 / 导入成功，自动将该账号历史所有未解除的风控/失效事件标记为已解除
    unresolved = await session.execute(
        select(RiskEvent).where(RiskEvent.account_id == acc.id, RiskEvent.resolved_at.is_(None))
    )
    now = datetime.now(UTC)
    for ev in unresolved.scalars():
        ev.resolved_at = now
    await session.commit()
    await DbSessionStore().save_cookies(acc.id, cookies)
    rt = get_runtime()
    await rt.gateway.invalidate(acc.id)
    guard_rt = rt.guard.runtime(account_key(acc.id))
    guard_rt.last_error = None
    guard_rt.punish_url = None
    rt.guard.load(account_key(acc.id), AccountState.ACTIVE, 0, acc.strikes)
    # 通知 IM 网关用新的登录态（重新）建立长连接
    await bus.publish(
        Topics.ACCOUNT_STATUS_CHANGED,
        {"account_id": acc.id, "state": AccountState.ACTIVE, "reason": "登录", "restart": True},
    )
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
                avatar = data.get("avatar") or data.get("userIcon") or data.get("portrait") or data.get("headUrl")
                if avatar:
                    acc.avatar = avatar
                guard_state = rt.guard.runtime(account_key(account_id)).state
                sync_runtime_to_model(acc, rt.guard.runtime(account_key(account_id)))
                if guard_state == AccountState.ACTIVE:
                    # 账号完全正常，自动解决所有未解除的风控与失效事件
                    unresolved = await s.execute(
                        select(RiskEvent).where(
                            RiskEvent.account_id == account_id,
                            RiskEvent.resolved_at.is_(None),
                        )
                    )
                    now = datetime.now(UTC)
                    for ev in unresolved.scalars():
                        ev.resolved_at = now
                elif guard_state != AccountState.NEED_LOGIN:
                    # 探活通过证明当前登录态有效，解决未解除的 need_login 事件
                    unresolved = await s.execute(
                        select(RiskEvent).where(
                            RiskEvent.account_id == account_id,
                            RiskEvent.resolved_at.is_(None),
                            RiskEvent.state == AccountState.NEED_LOGIN,
                        )
                    )
                    now = datetime.now(UTC)
                    for ev in unresolved.scalars():
                        ev.resolved_at = now
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
            async with session_factory()() as s:
                unresolved = await s.execute(
                    select(RiskEvent).where(
                        RiskEvent.account_id == account_id,
                        RiskEvent.resolved_at.is_(None),
                        RiskEvent.state == AccountState.NEED_LOGIN,
                    )
                )
                now = datetime.now(UTC)
                for ev in unresolved.scalars():
                    ev.resolved_at = now
                await s.commit()
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
    # 重新登录时：要登录回去的账号（扫了别的号不能覆盖 / 新增）
    expect_unb: str | None = None
    expect_name: str = ""
    relogin: bool = False  # 登录的是已有账号（保留设置与数据），而不是新增


def wrong_account_message(name: str) -> str:
    return f"登录的是另一个闲鱼账号，不是「{name}」。请用「{name}」登录的手机扫码 / 导出 Cookie"


class QrLoginManager:
    TTL = 300

    def __init__(self) -> None:
        self._entries: dict[str, _QrEntry] = {}

    async def _gc(self) -> None:
        now = time.time()
        for key in [k for k, e in self._entries.items() if now - e.created > self.TTL]:
            entry = self._entries.pop(key)
            await entry.client.aclose()

    async def start(self, owner: User, proxy: str | None = None, expect: XyAccount | None = None) -> tuple[str, str]:
        await self._gc()
        client = QrLoginClient(proxy=proxy)
        try:
            sess = await get_runtime().guard.run("login", Action.LOGIN, client.start)
        except BaseException as exc:
            await client.aclose()
            if isinstance(exc, RiskBlockedError):
                retry_after = math.ceil(exc.retry_after) if exc.retry_after is not None else None
                headers = {"Retry-After": str(retry_after)} if retry_after is not None else None
                if exc.state == "rate_limited":
                    raise HTTPException(
                        status.HTTP_429_TOO_MANY_REQUESTS,
                        f"生成二维码过于频繁，请在 {retry_after} 秒后重试",
                        headers=headers,
                    ) from exc
                raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc), headers=headers) from exc
            raise
        qr_id = secrets.token_urlsafe(12)
        self._entries[qr_id] = _QrEntry(
            owner_id=owner.id,
            proxy=proxy,
            client=client,
            session=sess,
            expect_unb=expect.unb if expect else None,
            expect_name=(expect.remark or expect.nickname or expect.unb) if expect else "",
        )
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
            await entry.client.aclose()
            unb = result.cookies.get("unb")
            if entry.expect_unb and unb != entry.expect_unb:
                entry.status, entry.message = QrStatus.ERROR, wrong_account_message(entry.expect_name)
                return entry
            async with session_factory()() as s:
                entry.relogin = (
                    await s.execute(select(XyAccount.id).where(XyAccount.unb == unb))
                ).scalar_one_or_none() is not None
                acc = await upsert_account(s, user, result.cookies, entry.proxy)
                entry.account_id = acc.id
            asyncio.create_task(probe_account(acc.id))
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
