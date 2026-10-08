import secrets
from datetime import UTC, datetime, timedelta

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.security import hash_password, verify_password
from app.domains.system.models import Role, User

MAX_FAILED_ATTEMPTS = 5
LOCK_MINUTES = 15


class AuthError(Exception):
    pass


async def authenticate(session: AsyncSession, username: str, password: str) -> User:
    user = (await session.execute(select(User).where(User.username == username))).scalar_one_or_none()
    now = datetime.now(UTC)
    if user is None or not user.is_active:
        raise AuthError("用户名或密码错误")
    locked_until = user.locked_until
    if locked_until is not None and locked_until.tzinfo is None:
        locked_until = locked_until.replace(tzinfo=UTC)
    if locked_until and locked_until > now:
        raise AuthError("登录失败次数过多，账号已临时锁定")
    if not verify_password(password, user.password_hash):
        user.failed_attempts += 1
        if user.failed_attempts >= MAX_FAILED_ATTEMPTS:
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            user.failed_attempts = 0
        await session.commit()
        raise AuthError("用户名或密码错误")
    user.failed_attempts = 0
    user.locked_until = None
    user.last_login_at = now
    await session.commit()
    return user


async def create_user(session: AsyncSession, username: str, password: str, role: str = Role.MEMBER) -> User:
    if len(password) < 8:
        raise ValueError("密码至少 8 位")
    user = User(username=username, password_hash=hash_password(password), role=role)
    session.add(user)
    await session.commit()
    await session.refresh(user)
    return user


async def ensure_admin() -> None:
    """首次启动时创建管理员。生产环境必须通过 ADMIN_PASSWORD 指定密码，不提供默认密码。"""
    settings = get_settings()
    async with session_factory()() as session:
        count = (await session.execute(select(func.count()).select_from(User))).scalar_one()
        if count:
            return
        password = settings.admin_password
        if not password:
            if settings.is_production:
                raise RuntimeError("首次启动必须设置 ADMIN_PASSWORD")
            password = secrets.token_urlsafe(12)
            logger.warning("已创建管理员 {}，随机初始密码：{}（请登录后立即修改）", settings.admin_username, password)
        await create_user(session, settings.admin_username, password, Role.ADMIN)
