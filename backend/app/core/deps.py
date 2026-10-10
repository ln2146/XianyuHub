"""FastAPI 依赖：数据库会话、当前用户、角色校验。所有业务路由都必须挂鉴权依赖。"""

from collections.abc import Callable
from typing import Annotated

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import user_id_from_token
from app.domains.system.models import Role, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]
_bearer = HTTPBearer(auto_error=False)


async def get_current_user(
    session: SessionDep,
    cred: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if cred is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "未登录", headers={"WWW-Authenticate": "Bearer"})
    try:
        user_id = user_id_from_token(cred.credentials)
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "登录已失效") from e
    user = await session.get(User, user_id)
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "用户不存在或已停用")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable:
    async def _check(user: CurrentUser) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "权限不足")
        return user

    return _check


AdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
OperatorUser = Annotated[User, Depends(require_roles(Role.ADMIN, Role.OPERATOR))]
