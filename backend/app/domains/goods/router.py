from datetime import UTC, datetime
from typing import Any

from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.core.deps import CurrentUser, SessionDep
from app.domains.account.service import accessible_account_ids, get_account_for
from app.domains.goods import service
from app.domains.goods.models import DraftStatus, MyItem, PublishDraftRecord
from app.domains.system.audit import record_audit
from app.goofish.errors import GoofishError, RiskBlockedError
from app.goofish.publish import ShippingMode
from app.intelligence.llm import LLMError, LLMUnavailable, get_llm
from app.runtime import get_runtime

router = APIRouter(prefix="/goods", tags=["goods"])


def goofish_http_error(e: Exception) -> HTTPException:
    if isinstance(e, RiskBlockedError):
        return HTTPException(status.HTTP_423_LOCKED, f"账号风控保护中：{e}")
    return HTTPException(status.HTTP_502_BAD_GATEWAY, f"闲鱼接口错误：{e}")


class ItemOut(BaseModel):
    model_config = {"from_attributes": True}

    id: int
    account_id: int
    item_id: str
    title: str
    price: float | None
    image_url: str
    status: str
    desc: str
    floor_price: float | None
    max_rounds: int
    step_ratios: list[float]
    gifts: str
    knowledge: str
    is_virtual: bool
    synced_at: datetime | None
    last_polished_at: datetime | None


class ItemUpdate(BaseModel):
    floor_price: float | None = Field(default=None, ge=0)
    max_rounds: int | None = Field(default=None, ge=0, le=10)
    step_ratios: list[float] | None = None
    gifts: str | None = None
    knowledge: str | None = Field(default=None, max_length=8000)
    desc: str | None = None
    is_virtual: bool | None = None


class DraftIn(BaseModel):
    account_id: int
    title: str = Field(min_length=1, max_length=60)
    desc: str = Field(min_length=1, max_length=5000)
    image_ids: list[str] = Field(min_length=1, max_length=9)
    price: float = Field(gt=0)
    orig_price: float | None = None
    quantity: int = Field(default=1, ge=1)
    shipping: ShippingMode = ShippingMode.FREE
    post_fee: float = 0
    self_pickup: bool = False
    floor_price: float | None = None
    knowledge: str = ""
    is_virtual: bool = False
    scheduled_at: datetime | None = None

    @model_validator(mode="after")
    def _check(self) -> "DraftIn":
        if self.floor_price is not None and self.floor_price > self.price:
            raise ValueError("底价不能高于售价")
        return self


class DraftOut(DraftIn):
    model_config = {"from_attributes": True}

    id: int
    status: str
    item_id: str | None
    error: str | None
    created_at: datetime


class CopyIn(BaseModel):
    image_ids: list[str] = Field(min_length=1, max_length=4)
    hint: str = ""


async def _own_item(session, user, item_pk: int) -> MyItem:
    item = await session.get(MyItem, item_pk)
    if item is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "商品不存在")
    await get_account_for(session, user, item.account_id)
    return item


# ---------------------------------------------------------------- 商品
@router.post("/accounts/{account_id}/sync")
async def sync(account_id: int, user: CurrentUser, session: SessionDep) -> dict[str, int]:
    await get_account_for(session, user, account_id)
    try:
        return await service.sync_items(account_id)
    except GoofishError as e:
        raise goofish_http_error(e) from e


@router.get("/items", response_model=list[ItemOut])
async def list_items(
    user: CurrentUser,
    session: SessionDep,
    account_id: int | None = None,
    status_: str | None = Query(None, alias="status"),
    q: str | None = None,
) -> list[MyItem]:
    ids = await accessible_account_ids(session, user)
    stmt = select(MyItem).order_by(MyItem.id.desc())
    if ids is not None:
        stmt = stmt.where(MyItem.account_id.in_(ids))
    if account_id is not None:
        stmt = stmt.where(MyItem.account_id == account_id)
    if status_:
        stmt = stmt.where(MyItem.status == status_)
    if q:
        stmt = stmt.where(MyItem.title.contains(q))
    return list((await session.execute(stmt.limit(500))).scalars())


@router.patch("/items/{item_pk}", response_model=ItemOut)
async def update_item(item_pk: int, body: ItemUpdate, user: CurrentUser, session: SessionDep) -> MyItem:
    item = await _own_item(session, user, item_pk)
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(item, k, v)
    if item.floor_price is not None and item.price is not None and item.floor_price > item.price:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "底价不能高于售价")
    await session.commit()
    await record_audit(
        "goods.update",
        user_id=user.id,
        actor_type="human",
        account_id=item.account_id,
        target_type="item",
        target_id=item.item_id,
        detail=body.model_dump(exclude_none=True, exclude={"knowledge"}),
    )
    return item


@router.post("/items/{item_pk}/polish")
async def polish(item_pk: int, user: CurrentUser, session: SessionDep) -> dict[str, bool]:
    item = await _own_item(session, user, item_pk)
    try:
        await service.polish_item(item, user.id)
    except GoofishError as e:
        raise goofish_http_error(e) from e
    return {"ok": True}


@router.post("/items/{item_pk}/offline")
async def offline(item_pk: int, user: CurrentUser, session: SessionDep) -> dict[str, bool]:
    item = await _own_item(session, user, item_pk)
    try:
        await get_runtime().gateway.offline_item(item.account_id, item.item_id)
    except GoofishError as e:
        raise goofish_http_error(e) from e
    item.status = "offline"
    await session.commit()
    await record_audit(
        "goods.offline",
        user_id=user.id,
        actor_type="human",
        account_id=item.account_id,
        target_type="item",
        target_id=item.item_id,
    )
    return {"ok": True}


@router.get("/market")
async def market(_: CurrentUser, keyword: str = Query(min_length=1), my_price: float | None = None) -> dict[str, Any]:
    try:
        return (await service.market_for(keyword, my_price)).model_dump()
    except GoofishError as e:
        raise goofish_http_error(e) from e


# ---------------------------------------------------------------- 图片与 AI 文案
@router.post("/uploads")
async def upload(_: CurrentUser, file: UploadFile = File(...)) -> dict[str, str]:
    content = await file.read()
    try:
        image_id = service.save_upload(content, file.content_type or "")
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"id": image_id, "url": f"/api/v1/goods/uploads/{image_id}"}


@router.get("/uploads/{image_id}")
async def get_upload(image_id: str) -> Response:
    # 文件名为随机 UUID，作为 <img> 直接引用，不要求鉴权头
    try:
        data, media = service.load_upload(image_id)
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "图片不存在") from e
    return Response(content=data, media_type=media, headers={"Cache-Control": "private, max-age=86400"})


@router.post("/ai-copy")
async def ai_copy(body: CopyIn, _: CurrentUser) -> dict[str, Any]:
    llm = get_llm()
    try:
        out = await service.ai_copy(llm, body.image_ids, body.hint)
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片不存在") from e
    except LLMUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"大模型不可用：{e}") from e
    except LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    result: dict[str, Any] = out.model_dump()
    try:
        result["market"] = (await service.market_for(out.search_keyword)).model_dump()
    except GoofishError:
        result["market"] = None
    return result


# ---------------------------------------------------------------- 草稿与发布
@router.get("/drafts", response_model=list[DraftOut])
async def list_drafts(user: CurrentUser, session: SessionDep) -> list[PublishDraftRecord]:
    ids = await accessible_account_ids(session, user)
    stmt = select(PublishDraftRecord).order_by(PublishDraftRecord.id.desc()).limit(200)
    if ids is not None:
        stmt = stmt.where(PublishDraftRecord.account_id.in_(ids))
    return list((await session.execute(stmt)).scalars())


@router.post("/drafts", response_model=DraftOut, status_code=201)
async def create_draft(body: DraftIn, user: CurrentUser, session: SessionDep) -> PublishDraftRecord:
    await get_account_for(session, user, body.account_id)
    d = PublishDraftRecord(**body.model_dump(), created_by=user.id)
    d.status = DraftStatus.SCHEDULED if body.scheduled_at else DraftStatus.DRAFT
    session.add(d)
    await session.commit()
    return d


@router.put("/drafts/{draft_id}", response_model=DraftOut)
async def update_draft(draft_id: int, body: DraftIn, user: CurrentUser, session: SessionDep) -> PublishDraftRecord:
    d = await session.get(PublishDraftRecord, draft_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "草稿不存在")
    await get_account_for(session, user, d.account_id)
    if d.status in (DraftStatus.PUBLISHING, DraftStatus.PUBLISHED):
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的草稿不能修改")
    for k, v in body.model_dump().items():
        setattr(d, k, v)
    d.status = DraftStatus.SCHEDULED if body.scheduled_at else DraftStatus.DRAFT
    await session.commit()
    return d


@router.delete("/drafts/{draft_id}", status_code=204)
async def delete_draft(draft_id: int, user: CurrentUser, session: SessionDep) -> None:
    d = await session.get(PublishDraftRecord, draft_id)
    if d is None:
        return
    await get_account_for(session, user, d.account_id)
    await session.delete(d)
    await session.commit()


@router.post("/drafts/{draft_id}/publish")
async def publish(draft_id: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    """人工确认后立即发布（发布受账号级令牌桶限制：默认每 5 分钟 1 个）。"""
    d = await session.get(PublishDraftRecord, draft_id)
    if d is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "草稿不存在")
    await get_account_for(session, user, d.account_id)
    try:
        item_id = await service.publish_draft(draft_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except GoofishError as e:
        raise goofish_http_error(e) from e
    return {"item_id": item_id, "published_at": datetime.now(UTC)}
