"""页面上手动触发的闲鱼读请求的通道选择：未指定账号时走匿名通道，
匿名受限则静默改用一个绑定的账号（不打扰用户）。后台定时任务不走这里，按各自配置的通道执行。"""

import time
from collections.abc import Awaitable, Callable

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.account.models import XyAccount
from app.domains.account.service import accessible_account_ids
from app.domains.system.models import User
from app.goofish.errors import RiskBlockedError, RiskControlError
from app.goofish.gateway import account_key
from app.runtime import get_runtime


def anon_paused() -> bool:
    """匿名通道是否在暂停保护中。"""
    rt = get_runtime().gateway.guard.runtime(account_key(None))
    return rt.state in ("cooldown", "circuit_open") and rt.cooldown_until > time.time()


async def fallback_account(session: AsyncSession, user: User) -> XyAccount | None:
    """可代为请求的账号：用户可访问、已登录、当前未被限制。"""
    stmt = select(XyAccount).where(XyAccount.status == "active").order_by(XyAccount.id)
    allowed = await accessible_account_ids(session, user)
    if allowed is not None:
        stmt = stmt.where(XyAccount.id.in_(allowed))
    guard = get_runtime().gateway.guard
    for acc in (await session.execute(stmt)).scalars():
        if guard.runtime(account_key(acc.id)).state == "active":
            return acc
    return None


async def with_fallback[T](
    session: AsyncSession,
    user: User,
    account_id: int | None,
    fn: Callable[[int | None], Awaitable[T]],
    *,
    fallback: bool = True,
) -> tuple[T, XyAccount | None]:
    """执行一次闲鱼请求，返回 (结果, 代为请求的账号)。匿名已在暂停保护中就不再去试探
    （会延长闲鱼的限制），直接用账号；匿名这次被限制则换账号重试一次。"""
    used: XyAccount | None = None
    channel = account_id
    if account_id is None and fallback and anon_paused():
        used = await fallback_account(session, user)
        channel = used.id if used else None
    try:
        return await fn(channel), used
    except (RiskBlockedError, RiskControlError):
        if channel is not None or not fallback or (used := await fallback_account(session, user)) is None:
            raise
    return await fn(used.id), used
