from typing import Any

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.deps import CurrentUser, SessionDep
from app.notify.models import NotificationChannel
from app.notify.senders import OPTIONAL_FIELDS, SENDERS, Notification, validate_config
from app.notify.service import NotifyEvents, decode_config, encode_config, send_to_channel

router = APIRouter(prefix="/notify", tags=["notify"])

_SECRET_KEYS = {"webhook_url", "bot_token", "device_key", "token", "password", "url", "sendkey", "secret", "topic"}


def _masked(cfg: dict[str, Any]) -> dict[str, Any]:
    out = {}
    for k, v in cfg.items():
        if k in _SECRET_KEYS and isinstance(v, str) and len(v) > 8:
            out[k] = v[:6] + "***" + v[-2:]
        else:
            out[k] = v
    return out


class ChannelIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    type: str
    config: dict[str, Any]
    events: list[str] = Field(default_factory=list)
    enabled: bool = True


class ChannelUpdate(BaseModel):
    name: str | None = None
    config: dict[str, Any] | None = None
    events: list[str] | None = None
    enabled: bool | None = None


class ChannelOut(BaseModel):
    id: int
    name: str
    type: str
    config: dict[str, Any]
    events: list[str]
    enabled: bool
    last_error: str | None


def _out(ch: NotificationChannel) -> ChannelOut:
    return ChannelOut(
        id=ch.id,
        name=ch.name,
        type=ch.type,
        config=_masked(decode_config(ch)),
        events=ch.events or [],
        enabled=ch.enabled,
        last_error=ch.last_error,
    )


async def _get(session, user, channel_id: int) -> NotificationChannel:
    ch = await session.get(NotificationChannel, channel_id)
    if ch is None or ch.owner_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "通知渠道不存在")
    return ch


@router.get("/meta")
async def meta(_: CurrentUser) -> dict[str, Any]:
    return {
        "types": {k: v[1] for k, v in SENDERS.items()},
        "optional": {k: OPTIONAL_FIELDS.get(k, {}) for k in SENDERS},
        "events": NotifyEvents.ALL,
    }


@router.get("/channels", response_model=list[ChannelOut])
async def list_channels(user: CurrentUser, session: SessionDep) -> list[ChannelOut]:
    rows = await session.execute(select(NotificationChannel).where(NotificationChannel.owner_id == user.id))
    return [_out(c) for c in rows.scalars()]


@router.post("/channels", response_model=ChannelOut, status_code=201)
async def create_channel(body: ChannelIn, user: CurrentUser, session: SessionDep) -> ChannelOut:
    try:
        validate_config(body.type, body.config)
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    ch = NotificationChannel(
        owner_id=user.id,
        name=body.name,
        type=body.type,
        config_enc=encode_config(body.config),
        events=body.events,
        enabled=body.enabled,
    )
    session.add(ch)
    await session.commit()
    return _out(ch)


@router.patch("/channels/{channel_id}", response_model=ChannelOut)
async def update_channel(channel_id: int, body: ChannelUpdate, user: CurrentUser, session: SessionDep) -> ChannelOut:
    ch = await _get(session, user, channel_id)
    if body.config is not None:
        # 未修改的敏感字段前端会回传打码值，此时保留原值
        merged = decode_config(ch)
        for k, v in body.config.items():
            if not (isinstance(v, str) and "***" in v):
                merged[k] = v
        try:
            validate_config(ch.type, merged)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
        ch.config_enc = encode_config(merged)
    for field in ("name", "events", "enabled"):
        value = getattr(body, field)
        if value is not None:
            setattr(ch, field, value)
    await session.commit()
    return _out(ch)


@router.delete("/channels/{channel_id}", status_code=204)
async def delete_channel(channel_id: int, user: CurrentUser, session: SessionDep) -> None:
    ch = await _get(session, user, channel_id)
    await session.delete(ch)
    await session.commit()


@router.post("/channels/{channel_id}/test")
async def test_channel(channel_id: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    ch = await _get(session, user, channel_id)
    try:
        await send_to_channel(
            ch, Notification(event="test", title="鱼塘管家测试通知", content="如果你看到这条消息，说明渠道配置正确。")
        )
        ch.last_error = None
        ok, err = True, None
    except Exception as e:  # noqa: BLE001
        ch.last_error = str(e)[:500]
        ok, err = False, ch.last_error
    await session.commit()
    return {"ok": ok, "error": err}


class ProbeIn(BaseModel):
    type: str
    config: dict[str, Any]
    name: str = "测试连接器"


@router.post("/test")
async def test_unsaved_channel(body: ProbeIn, user: CurrentUser) -> dict[str, Any]:
    """无需先保存即可实时测试连接器有效性。"""
    try:
        validate_config(body.type, body.config)
        ch = NotificationChannel(
            owner_id=user.id,
            name=body.name,
            type=body.type,
            config_enc=encode_config(body.config),
            events=[],
            enabled=True,
        )
        await send_to_channel(
            ch, Notification(event="test", title="鱼塘管家测试通知", content="如果你看到这条消息，说明连接器配置正确。")
        )
        return {"ok": True, "error": None}
    except Exception as e:  # noqa: BLE001
        return {"ok": False, "error": str(e)[:500]}
