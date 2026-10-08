from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import session_factory
from app.domains.system.models import ActorType, AuditLog


async def record_audit(
    action: str,
    *,
    session: AsyncSession | None = None,
    user_id: int | None = None,
    actor_type: str = ActorType.SYSTEM,
    account_id: int | None = None,
    target_type: str | None = None,
    target_id: str | int | None = None,
    success: bool = True,
    detail: dict[str, Any] | None = None,
    error: str | None = None,
) -> None:
    """写入审计日志。传入 session 时随业务事务一起提交，否则独立提交。"""
    log = AuditLog(
        action=action,
        user_id=user_id,
        actor_type=actor_type,
        account_id=account_id,
        target_type=target_type,
        target_id=str(target_id) if target_id is not None else None,
        success=success,
        detail=detail or {},
        error=error,
    )
    if session is not None:
        session.add(log)
        return
    async with session_factory()() as s:
        s.add(log)
        await s.commit()
