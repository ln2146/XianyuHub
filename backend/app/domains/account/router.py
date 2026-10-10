import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from app.core.crypto import get_vault
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.domains.account import service
from app.domains.account.models import AccountGrant, AccountSettings, RiskEvent, XyAccount
from app.domains.account.store import DbSessionStore
from app.domains.system.audit import record_audit
from app.domains.system.models import User
from app.goofish.gateway import account_key
from app.goofish.guard.guard import AccountState
from app.runtime import get_runtime

router = APIRouter(prefix="/accounts", tags=["accounts"])


class AccountOut(BaseModel):
    id: int
    owner_id: int
    unb: str
    nickname: str
    remark: str
    avatar: str
    status: str
    health_score: int
    strikes: int
    cooldown_until: datetime | None
    last_error: str | None
    punish_url: str | None
    has_proxy: bool
    settings: AccountSettings
    last_probe_at: datetime | None
    created_at: datetime


def to_out(acc: XyAccount) -> AccountOut:
    rt = get_runtime().guard.runtime(account_key(acc.id))
    return AccountOut(
        id=acc.id,
        owner_id=acc.owner_id,
        unb=acc.unb,
        nickname=acc.nickname,
        remark=acc.remark,
        avatar=acc.avatar,
        status=rt.state,
        health_score=rt.health,
        strikes=rt.strikes,
        cooldown_until=acc.cooldown_until,
        last_error=rt.last_error or acc.last_error,
        punish_url=rt.punish_url or acc.punish_url,
        has_proxy=bool(acc.proxy_enc),
        settings=acc.get_settings(),
        last_probe_at=acc.last_probe_at,
        created_at=acc.created_at,
    )


class ImportIn(BaseModel):
    cookies: str
    proxy: str | None = None
    verify: bool = True
    account_id: int | None = None


class QrStartIn(BaseModel):
    proxy: str | None = None
    account_id: int | None = None


class AccountUpdate(BaseModel):
    remark: str | None = None
    proxy: str | None = None  # 空字符串表示清除
    settings: dict[str, Any] | None = None
    enabled: bool | None = None


class GrantIn(BaseModel):
    user_id: int


class RiskEventOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    state: str
    reason: str
    punish_url: str | None
    created_at: datetime
    resolved_at: datetime | None


@router.get("", response_model=list[AccountOut])
async def list_accounts(user: CurrentUser, session: SessionDep) -> list[AccountOut]:
    ids = await service.accessible_account_ids(session, user)
    stmt = select(XyAccount).order_by(XyAccount.id)
    if ids is not None:
        stmt = stmt.where(XyAccount.id.in_(ids))
    return [to_out(a) for a in (await session.execute(stmt)).scalars()]


@router.post("/import", response_model=AccountOut, status_code=201)
async def import_cookies(body: ImportIn, user: CurrentUser, session: SessionDep) -> AccountOut:
    cookies = service.parse_cookie_input(body.cookies)
    proxy = body.proxy
    if proxy is None and body.account_id:
        proxy = await DbSessionStore().get_proxy(body.account_id)
    acc = await service.upsert_account(session, user, cookies, proxy)
    if body.verify:
        if not await service.probe_account(acc.id):
            rt = get_runtime().guard.runtime(account_key(acc.id))
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Cookie 校验失败：{rt.last_error or '登录态无效'}")
    else:
        asyncio.create_task(service.probe_account(acc.id))
    await session.refresh(acc)
    return to_out(acc)


@router.post("/qr")
async def qr_start(body: QrStartIn, user: CurrentUser) -> dict[str, str]:
    proxy = body.proxy
    if proxy is None and body.account_id:
        proxy = await DbSessionStore().get_proxy(body.account_id)
    qr_id, content = await service.qr_manager.start(user, proxy)
    return {"qr_id": qr_id, "qr_content": content}


@router.get("/qr/{qr_id}")
async def qr_poll(qr_id: str, user: CurrentUser) -> dict[str, Any]:
    entry = await service.qr_manager.poll(qr_id, user)
    return {
        "status": entry.status,
        "account_id": entry.account_id,
        "verify_url": entry.verify_url,
        "message": entry.message,
    }


@router.get("/{account_id}", response_model=AccountOut)
async def get_account(account_id: int, user: CurrentUser, session: SessionDep) -> AccountOut:
    return to_out(await service.get_account_for(session, user, account_id))


@router.patch("/{account_id}", response_model=AccountOut)
async def update_account(account_id: int, body: AccountUpdate, user: CurrentUser, session: SessionDep) -> AccountOut:
    acc = await service.get_account_for(session, user, account_id)
    if body.remark is not None:
        acc.remark = body.remark
    if body.proxy is not None:
        acc.proxy_enc = get_vault().encrypt(body.proxy) if body.proxy else None
        await get_runtime().gateway.invalidate(acc.id)
    if body.settings is not None:
        merged = {**(acc.settings or {}), **body.settings}
        acc.settings = AccountSettings.model_validate(merged).model_dump()
    if body.enabled is not None:
        await get_runtime().guard.set_state(
            account_key(acc.id), AccountState.ACTIVE if body.enabled else AccountState.DISABLED, "手动启停"
        )
        acc.status = AccountState.ACTIVE if body.enabled else AccountState.DISABLED
    await session.commit()
    await record_audit(
        "account.update",
        user_id=user.id,
        actor_type="human",
        account_id=acc.id,
        detail=body.model_dump(exclude={"proxy"}, exclude_none=True),
    )
    return to_out(acc)


@router.delete("/{account_id}", status_code=204)
async def delete_account(account_id: int, user: CurrentUser, session: SessionDep) -> None:
    acc = await service.get_account_for(session, user, account_id)
    await get_runtime().gateway.invalidate(acc.id)
    await session.delete(acc)
    await session.commit()
    await record_audit("account.delete", user_id=user.id, actor_type="human", account_id=account_id)


@router.post("/{account_id}/probe")
async def probe(account_id: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    await service.get_account_for(session, user, account_id)
    ok = await service.probe_account(account_id)
    return {"ok": ok, "status": get_runtime().guard.runtime(account_key(account_id)).state}


@router.post("/{account_id}/resolve")
async def resolve(account_id: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    await service.get_account_for(session, user, account_id)
    await service.resolve_risk(account_id, user)
    return {"status": get_runtime().guard.runtime(account_key(account_id)).state}


@router.get("/{account_id}/risk-events", response_model=list[RiskEventOut])
async def risk_events(account_id: int, user: CurrentUser, session: SessionDep) -> list[RiskEvent]:
    await service.get_account_for(session, user, account_id)
    rows = await session.execute(
        select(RiskEvent).where(RiskEvent.account_id == account_id).order_by(RiskEvent.id.desc()).limit(100)
    )
    return list(rows.scalars())


@router.get("/{account_id}/grants")
async def list_grants(account_id: int, _: AdminUser, session: SessionDep) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(AccountGrant, User)
        .join(User, User.id == AccountGrant.user_id)
        .where(AccountGrant.account_id == account_id)
        .order_by(AccountGrant.id)
    )
    return [{"user_id": u.id, "username": u.username, "role": u.role} for _g, u in rows]


@router.post("/{account_id}/grants", status_code=201)
async def grant(account_id: int, body: GrantIn, _: AdminUser, session: SessionDep) -> dict[str, int]:
    if await session.get(XyAccount, account_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "账号不存在")
    exists = (
        await session.execute(
            select(AccountGrant).where(AccountGrant.user_id == body.user_id, AccountGrant.account_id == account_id)
        )
    ).scalar_one_or_none()
    if exists is None:
        session.add(AccountGrant(user_id=body.user_id, account_id=account_id))
        await session.commit()
    return {"user_id": body.user_id, "account_id": account_id}


@router.delete("/{account_id}/grants/{user_id}", status_code=204)
async def revoke(account_id: int, user_id: int, _: AdminUser, session: SessionDep) -> None:
    row = (
        await session.execute(
            select(AccountGrant).where(AccountGrant.user_id == user_id, AccountGrant.account_id == account_id)
        )
    ).scalar_one_or_none()
    if row:
        await session.delete(row)
        await session.commit()
