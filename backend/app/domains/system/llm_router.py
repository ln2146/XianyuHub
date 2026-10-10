"""大模型接入配置的接口：管理台增删改、切换生效、测试连通性与拉取模型列表。

只有管理员可以修改；普通成员只能查看当前生效配置与用量。
"""

from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.config import get_settings
from app.core.crypto import get_vault
from app.core.deps import AdminUser, CurrentUser, SessionDep
from app.domains.system import llm as llm_service
from app.domains.system.audit import record_audit
from app.domains.system.models import LlmProvider
from app.intelligence.llm import LLMError, LlmConfig, get_config, get_llm

router = APIRouter(prefix="/llm", tags=["llm"])

KINDS = ("anthropic", "openai_compatible")


class ProviderIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    kind: str = "openai_compatible"
    base_url: str = Field(default="", max_length=256)
    api_key: str = ""
    model_vision: str = ""
    model_chat: str = ""
    model_fast: str = ""
    custom_models: list[str] = Field(default_factory=list)
    timeout_seconds: float = Field(default=90, gt=0, le=600)
    anthropic_fallbacks: bool = True
    daily_token_budget: int | None = Field(default=None, ge=0)
    enabled: bool = True
    activate: bool = False


class ProviderUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=64)
    kind: str | None = None
    base_url: str | None = Field(default=None, max_length=256)
    api_key: str | None = None  # 留空或回传打码值表示不修改
    model_vision: str | None = None
    model_chat: str | None = None
    model_fast: str | None = None
    custom_models: list[str] | None = None
    timeout_seconds: float | None = Field(default=None, gt=0, le=600)
    anthropic_fallbacks: bool | None = None
    daily_token_budget: int | None = Field(default=None, ge=0)
    enabled: bool | None = None


class TierItem(BaseModel):
    provider_id: int | None = None
    model: str = ""


class TierConfigIn(BaseModel):
    chat: TierItem | None = None
    vision: TierItem | None = None
    fast: TierItem | None = None


class TestIn(BaseModel):
    """不传 id 时用请求体里的临时配置测试（新建时可以先测再存）。"""

    id: int | None = None
    name: str = ""
    kind: str = "openai_compatible"
    base_url: str = ""
    api_key: str = ""
    model_vision: str = ""
    model_chat: str = ""
    model_fast: str = ""
    timeout_seconds: float = Field(default=90, gt=0, le=600)
    anthropic_fallbacks: bool = True


class ProviderOut(BaseModel):
    id: int
    name: str
    kind: str
    base_url: str
    api_key_masked: str
    has_api_key: bool
    model_vision: str
    model_chat: str
    model_fast: str
    custom_models: list[str] = Field(default_factory=list)
    active_tiers: list[str] = Field(default_factory=list)
    timeout_seconds: float
    anthropic_fallbacks: bool
    daily_token_budget: int | None
    enabled: bool
    is_active: bool
    last_test_at: datetime | None
    last_test_ok: bool | None
    last_error: str | None


def _out(row: LlmProvider, active_tiers: list[str] | None = None) -> ProviderOut:
    key = get_vault().decrypt(row.api_key_enc) or ""
    return ProviderOut(
        id=row.id,
        name=row.name,
        kind=row.kind,
        base_url=row.base_url,
        api_key_masked=llm_service.mask_key(key),
        has_api_key=bool(key),
        model_vision=row.model_vision,
        model_chat=row.model_chat,
        model_fast=row.model_fast,
        custom_models=row.custom_models or [],
        active_tiers=active_tiers or [],
        timeout_seconds=row.timeout_seconds,
        anthropic_fallbacks=row.anthropic_fallbacks,
        daily_token_budget=row.daily_token_budget,
        enabled=row.enabled,
        is_active=row.is_active,
        last_test_at=row.last_test_at,
        last_test_ok=row.last_test_ok,
        last_error=row.last_error,
    )


def _validate_kind(kind: str) -> None:
    if kind not in KINDS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"不支持的供应商类型：{kind}")


async def _get(session, provider_id: int) -> LlmProvider:
    row = await session.get(LlmProvider, provider_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "接入配置不存在")
    return row


KEY_REBIND_MSG = "修改了接口地址或接口类型，请重新填写 API Key（已保存的 Key 不会发往新的地址）"


def _new_key(value: str | None) -> bool:
    """请求里是否带了新的 Key（空值或回传的打码值都不算）。"""
    return bool(value) and "***" not in (value or "")


def _endpoint_changed(row: LlmProvider, kind: str | None, base_url: str | None) -> bool:
    if kind is not None and kind != row.kind:
        return True
    return base_url is not None and base_url.strip().rstrip("/") != (row.base_url or "").strip().rstrip("/")


def _config_from_body(body: TestIn, base: LlmProvider | None = None) -> LlmConfig:
    key = body.api_key
    if base is not None and not _new_key(key):
        key = get_vault().decrypt(base.api_key_enc) or ""
        # 已保存的 Key 只能发往保存时的地址：改了地址或类型就必须重新填写
        if key and _endpoint_changed(base, body.kind, body.base_url or None):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, KEY_REBIND_MSG)
    settings = get_settings()
    return LlmConfig(
        kind=body.kind,
        api_key=key,
        base_url=body.base_url or (base.base_url if base else ""),
        model_vision=body.model_vision or (base.model_vision if base else ""),
        model_chat=body.model_chat or (base.model_chat if base else ""),
        model_fast=body.model_fast or (base.model_fast if base else ""),
        timeout=body.timeout_seconds,
        fallbacks=body.anthropic_fallbacks,
        daily_token_budget=settings.llm_daily_token_budget,
        max_images=settings.llm_max_images,
        source=body.name or (base.name if base else "临时配置"),
    )


@router.get("/meta")
async def meta(_: CurrentUser) -> dict[str, Any]:
    return {"kinds": list(KINDS), "presets": llm_service.PRESETS}


@router.get("/status")
async def llm_status(_: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """当前生效的模型配置与今日用量（总览页与设置页共用）。"""
    config = get_config()
    tier_bindings = await llm_service.get_tier_bindings(session)
    return {
        "active_source": config.source,
        "using_env": config.source == "env",
        "config": {
            "kind": config.kind,
            "base_url": config.base_url,
            "model_vision": config.model_vision,
            "model_chat": config.model_chat,
            "model_fast": config.model_fast,
        },
        "tiers": tier_bindings,
        "gateway": get_llm().status(),
    }


@router.get("/tiers")
async def get_tiers(_: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """获取当前分场景模型绑定（客服回复、看图发品、快速意图）。"""
    return {"tiers": await llm_service.get_tier_bindings(session)}


@router.put("/tiers")
async def update_tiers(body: TierConfigIn, admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    """更新分场景模型绑定。"""
    payload: dict[str, dict[str, Any]] = {}
    if body.chat is not None:
        payload["chat"] = {"provider_id": body.chat.provider_id, "model": body.chat.model}
    if body.vision is not None:
        payload["vision"] = {"provider_id": body.vision.provider_id, "model": body.vision.model}
    if body.fast is not None:
        payload["fast"] = {"provider_id": body.fast.provider_id, "model": body.fast.model}
    await llm_service.set_tier_bindings(session, payload)
    await llm_service.refresh()
    await record_audit(
        "llm.tiers.update",
        user_id=admin.id,
        actor_type="human",
        target_type="llm_tiers",
        detail=payload,
    )
    return {"tiers": await llm_service.get_tier_bindings(session)}


@router.get("/providers", response_model=list[ProviderOut])
async def list_providers(_: AdminUser, session: SessionDep) -> list[ProviderOut]:
    rows = (await session.execute(select(LlmProvider).order_by(LlmProvider.is_active.desc(), LlmProvider.id))).scalars().all()
    bindings = await llm_service.get_tier_bindings(session)
    tier_map: dict[int, list[str]] = {}
    for tier_name, item in bindings.items():
        pid = item.get("provider_id")
        if pid:
            tier_map.setdefault(pid, []).append(tier_name)
    return [_out(r, tier_map.get(r.id, [])) for r in rows]


@router.post("/providers", response_model=ProviderOut, status_code=201)
async def create_provider(body: ProviderIn, admin: AdminUser, session: SessionDep) -> ProviderOut:
    _validate_kind(body.kind)
    exists = (await session.execute(select(LlmProvider).where(LlmProvider.name == body.name))).scalar_one_or_none()
    if exists:
        raise HTTPException(status.HTTP_409_CONFLICT, "同名配置已存在")
    row = LlmProvider(
        name=body.name,
        kind=body.kind,
        base_url=body.base_url,
        api_key_enc=llm_service.encode_key(body.api_key),
        model_vision=body.model_vision,
        model_chat=body.model_chat,
        model_fast=body.model_fast,
        custom_models=body.custom_models or [],
        timeout_seconds=body.timeout_seconds,
        anthropic_fallbacks=body.anthropic_fallbacks,
        daily_token_budget=body.daily_token_budget,
        enabled=body.enabled,
        is_active=False,
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)

    # 自动填补：把可用模型自动填补到尚未绑定的场景，或显式激活时覆盖
    current_bindings = await llm_service.get_tier_bindings(session)
    auto_bind: dict[str, dict[str, Any]] = {}
    for tier in ("chat", "vision", "fast"):
        m = getattr(row, f"model_{tier}", "")
        has_binding = bool(current_bindings.get(tier, {}).get("provider_id"))
        if m and (not has_binding or body.activate):
            auto_bind[tier] = {"provider_id": row.id, "model": m}
    if auto_bind:
        await llm_service.set_tier_bindings(session, auto_bind)

    if body.activate:
        await llm_service.activate(session, row)

    await llm_service.refresh()

    await record_audit(
        "llm.provider.create",
        user_id=admin.id,
        actor_type="human",
        target_type="llm_provider",
        target_id=row.id,
        detail={"name": row.name, "kind": row.kind, "activate": body.activate},
    )
    bindings_after = await llm_service.get_tier_bindings(session)
    active_tiers = [t for t, item in bindings_after.items() if item.get("provider_id") == row.id]
    return _out(row, active_tiers)


@router.patch("/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(provider_id: int, body: ProviderUpdate, admin: AdminUser, session: SessionDep) -> ProviderOut:
    row = await _get(session, provider_id)
    has_saved_key = bool(get_vault().decrypt(row.api_key_enc))
    if has_saved_key and not _new_key(body.api_key) and _endpoint_changed(row, body.kind, body.base_url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, KEY_REBIND_MSG)
    if body.kind is not None:
        _validate_kind(body.kind)
        row.kind = body.kind
    if body.name is not None and body.name != row.name:
        dup = (await session.execute(select(LlmProvider).where(LlmProvider.name == body.name))).scalar_one_or_none()
        if dup is not None:
            raise HTTPException(status.HTTP_409_CONFLICT, "同名配置已存在")
        row.name = body.name
    for field in ("base_url", "model_vision", "model_chat", "model_fast", "timeout_seconds"):
        value = getattr(body, field)
        if value is not None:
            setattr(row, field, value)
    if body.anthropic_fallbacks is not None:
        row.anthropic_fallbacks = body.anthropic_fallbacks
    # 显式传 null 表示清空覆盖、回退到全局预算
    if "daily_token_budget" in body.model_fields_set:
        row.daily_token_budget = body.daily_token_budget
    if body.custom_models is not None:
        row.custom_models = body.custom_models
    if body.enabled is not None:
        row.enabled = body.enabled
        if not row.enabled and row.is_active:
            row.is_active = False
    # 前端回传打码值表示不修改 Key
    if body.api_key is not None and "***" not in body.api_key:
        row.api_key_enc = llm_service.encode_key(body.api_key)
    await session.commit()
    await session.refresh(row)
    if row.is_active:
        await llm_service.refresh()
    elif body.enabled is False:
        await llm_service.refresh()
    await record_audit(
        "llm.provider.update",
        user_id=admin.id,
        actor_type="human",
        target_type="llm_provider",
        target_id=row.id,
        detail={"name": row.name, "enabled": row.enabled},
    )
    bindings_after = await llm_service.get_tier_bindings(session)
    active_tiers = [t for t, item in bindings_after.items() if item.get("provider_id") == row.id]
    return _out(row, active_tiers)


@router.post("/providers/{provider_id}/activate", response_model=ProviderOut)
async def activate_provider(provider_id: int, admin: AdminUser, session: SessionDep) -> ProviderOut:
    row = await _get(session, provider_id)
    if not row.enabled:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "该配置已停用，请先启用")
    await llm_service.activate(session, row)
    await session.refresh(row)
    await llm_service.refresh()
    await record_audit(
        "llm.provider.activate",
        user_id=admin.id,
        actor_type="human",
        target_type="llm_provider",
        target_id=row.id,
        detail={"name": row.name},
    )
    bindings_after = await llm_service.get_tier_bindings(session)
    active_tiers = [t for t, item in bindings_after.items() if item.get("provider_id") == row.id]
    return _out(row, active_tiers)


@router.delete("/providers/{provider_id}", status_code=204)
async def delete_provider(provider_id: int, admin: AdminUser, session: SessionDep) -> None:
    row = await _get(session, provider_id)
    was_active = row.is_active
    bindings = await llm_service.get_tier_bindings(session)
    rebind = False
    for tier, item in bindings.items():
        if item.get("provider_id") == provider_id:
            item["provider_id"] = None
            item["model"] = ""
            rebind = True
    if rebind:
        await llm_service.set_tier_bindings(session, bindings)
    await session.delete(row)
    await session.commit()
    if was_active or rebind:
        await llm_service.refresh()
    await record_audit(
        "llm.provider.delete",
        user_id=admin.id,
        actor_type="human",
        target_type="llm_provider",
        target_id=provider_id,
        detail={"name": row.name},
    )


@router.post("/test")
async def test_provider(body: TestIn, admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    """测试连通性。传 id 用已保存的配置（Key 可留空），否则用请求体里的临时配置。"""
    row = await _get(session, body.id) if body.id is not None else None
    config = _config_from_body(body, row)
    ok, message, model = await llm_service.test_connection(config)
    if row is not None:
        row.last_test_at = datetime.now(UTC)
        row.last_test_ok = ok
        row.last_error = None if ok else message
        await session.commit()
    return {"ok": ok, "message": message, "model": model}


@router.post("/models")
async def fetch_models(body: TestIn, admin: AdminUser, session: SessionDep) -> dict[str, Any]:
    """拉取供应商的可用模型列表，供前端下拉选择。"""
    row = await _get(session, body.id) if body.id is not None else None
    config = _config_from_body(body, row)
    try:
        models = await llm_service.list_remote_models(config)
    except LLMError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    except Exception as e:  # noqa: BLE001
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)[:300]) from e
    return {"models": models}
