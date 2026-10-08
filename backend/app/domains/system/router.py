from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.core.security import create_access_token, hash_password, verify_password
from app.domains.system import service
from app.domains.system.models import AuditLog, Role, User

router = APIRouter(tags=["system"])


class LoginIn(BaseModel):
    username: str
    password: str


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: "UserOut"


class UserOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    username: str
    role: str
    is_active: bool
    last_login_at: datetime | None = None


class UserCreate(BaseModel):
    username: str = Field(min_length=3, max_length=64)
    password: str = Field(min_length=8)
    role: Role = Role.MEMBER


class UserUpdate(BaseModel):
    role: Role | None = None
    is_active: bool | None = None
    password: str | None = Field(default=None, min_length=8)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=8)


class AuditOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    created_at: datetime
    user_id: int | None
    actor_type: str
    action: str
    account_id: int | None
    target_type: str | None
    target_id: str | None
    success: bool
    detail: dict[str, Any]
    error: str | None


@router.post("/auth/login", response_model=TokenOut)
async def login(body: LoginIn, session: SessionDep) -> TokenOut:
    try:
        user = await service.authenticate(session, body.username, body.password)
    except service.AuthError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, str(e)) from e
    return TokenOut(access_token=create_access_token(user.id, user.role), user=UserOut.model_validate(user))


@router.get("/auth/me", response_model=UserOut)
async def me(user: CurrentUser) -> User:
    return user


@router.post("/auth/password", status_code=204)
async def change_password(body: PasswordChange, user: CurrentUser, session: SessionDep) -> None:
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "原密码错误")
    db_user = await session.get(User, user.id)
    assert db_user is not None
    db_user.password_hash = hash_password(body.new_password)
    await session.commit()


@router.get("/users", response_model=list[UserOut])
async def list_users(_: AdminUser, session: SessionDep) -> list[User]:
    return list((await session.execute(select(User).order_by(User.id))).scalars())


@router.post("/users", response_model=UserOut, status_code=201)
async def create_user(body: UserCreate, _: AdminUser, session: SessionDep) -> User:
    exists = (await session.execute(select(User).where(User.username == body.username))).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "用户名已存在")
    return await service.create_user(session, body.username, body.password, body.role)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(user_id: int, body: UserUpdate, admin: AdminUser, session: SessionDep) -> User:
    user = await session.get(User, user_id)
    if user is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "用户不存在")
    if user.id == admin.id and (body.is_active is False or (body.role and body.role != Role.ADMIN)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "不能停用或降级自己")
    if body.role is not None:
        user.role = body.role
    if body.is_active is not None:
        user.is_active = body.is_active
    if body.password:
        user.password_hash = hash_password(body.password)
    await session.commit()
    return user


@router.get("/audit-logs", response_model=list[AuditOut])
async def list_audit_logs(
    _: AdminUser,
    session: SessionDep,
    action: str | None = None,
    account_id: int | None = None,
    limit: int = Query(100, le=500),
    offset: int = 0,
) -> list[AuditLog]:
    stmt = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit).offset(offset)
    if action:
        stmt = stmt.where(AuditLog.action == action)
    if account_id is not None:
        stmt = stmt.where(AuditLog.account_id == account_id)
    return list((await session.execute(stmt)).scalars())
