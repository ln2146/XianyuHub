import asyncio
from datetime import UTC, datetime
from typing import Any

import httpx
from fastapi import APIRouter, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select

from app.core.deps import CurrentUser, SessionDep
from app.core.uploads import read_limited, sniff_image
from app.domains.account.channel import with_fallback
from app.domains.account.service import accessible_account_ids, get_account_for
from app.domains.goods import service
from app.domains.goods.ai_listing import Strategy, generate_listing
from app.domains.goods.models import DraftStatus, MyItem, PublishDraftRecord
from app.domains.system.audit import record_audit
from app.goofish.errors import GoofishError, RiskBlockedError, VerificationRequiredError
from app.goofish.publish import ItemLocation, ShippingMode
from app.intelligence.llm import LLMError, LLMUnavailable, get_llm
from app.runtime import get_runtime

router = APIRouter(prefix="/goods", tags=["goods"])
_background: set[asyncio.Task] = set()


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
    want_cnt: int | None = None
    browse_cnt: int | None = None
    publish_time: datetime | None = None
    stats_at: datetime | None = None


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
    location: ItemLocation | None = None  # 宝贝所在地；为空时沿用账号上次使用的所在地
    scheduled_at: datetime | None = None
    confirmed_facts: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check(self) -> "DraftIn":
        if self.floor_price is not None and self.floor_price > self.price:
            raise ValueError("底价不能高于售价")
        return self


class DraftOut(BaseModel):
    """输出不做输入校验：AI 草稿在无法估价时售价为 0，需要卖家在确认页补全。"""

    model_config = {"from_attributes": True}

    id: int
    account_id: int
    title: str
    desc: str
    image_ids: list[str]
    price: float
    orig_price: float | None
    quantity: int
    shipping: str
    post_fee: float
    self_pickup: bool
    floor_price: float | None
    knowledge: str
    is_virtual: bool
    location: dict[str, Any] | None = None
    scheduled_at: datetime | None
    status: str
    item_id: str | None
    error: str | None
    created_at: datetime
    ai_meta: dict[str, Any] | None = None
    confirmed_facts: list[str] = Field(default_factory=list)


class AiDraftIn(BaseModel):
    account_id: int
    image_ids: list[str] = Field(min_length=1, max_length=9)
    hint: str = Field(default="", max_length=500, description="一句话补充说明，如：自用一年，1500 出，最低 1300")
    strategy: Strategy = "market"
    draft_id: int | None = Field(default=None, description="传入时用新结果覆盖该草稿（重新生成）")


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
    for k, v in body.model_dump(exclude_unset=True).items():
        if v is None and k != "floor_price":  # floor_price 显式传 null 表示取消底价（关闭 AI 议价）
            continue
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


@router.post("/polish-all")
async def trigger_polish_all(user: CurrentUser, session: SessionDep, account_id: int | None = None) -> dict[str, str]:
    """手动立即触发自动擦亮任务（后台按安全间隔陆续执行）。只能擦亮自己有权限的账号。"""
    if account_id is not None:
        await get_account_for(session, user, account_id)
    allowed = await accessible_account_ids(session, user)  # 管理员为 None：不限
    task = asyncio.create_task(service.polish_all(account_id=account_id, only_accounts=allowed))
    _background.add(task)
    task.add_done_callback(_background.discard)
    return {"message": "已在后台启动擦亮任务，在售商品将按安全间隔陆续擦亮"}


@router.get("/market")
async def market(
    user: CurrentUser, session: SessionDep, keyword: str = Query(min_length=1), my_price: float | None = None
) -> dict[str, Any]:
    try:
        view, _ = await with_fallback(session, user, None, lambda aid: service.market_for(keyword, my_price, aid))
        return view.model_dump()
    except GoofishError as e:
        raise goofish_http_error(e) from e


# ---------------------------------------------------------------- 发布前置检查
@router.get("/publish-meta")
async def publish_meta(user: CurrentUser, session: SessionDep, account_id: int) -> dict[str, Any]:
    """账号当前能否发布、能否设多库存（发布页据此锁定数量）。"""
    await get_account_for(session, user, account_id)
    try:
        return await get_runtime().gateway.publish_capability(account_id)
    except GoofishError as e:
        raise goofish_http_error(e) from e


# ---------------------------------------------------------------- 宝贝所在地
@router.get("/locations")
async def locations(
    user: CurrentUser,
    session: SessionDep,
    account_id: int,
    longitude: float | None = Query(default=None, ge=73, le=136),
    latitude: float | None = Query(default=None, ge=3, le=54),
) -> dict[str, Any]:
    """宝贝所在地候选：账号常用地址、坐标附近的地点，以及上次发布用的所在地。坐标为 GCJ-02。"""
    acc = await get_account_for(session, user, account_id)
    out: dict[str, Any] = {"saved": (acc.settings or {}).get("publish_location"), "common": [], "nearby": []}
    if longitude is None or latitude is None:
        return out
    try:
        found = await get_runtime().gateway.locations(account_id, longitude, latitude)
    except GoofishError as e:
        raise goofish_http_error(e) from e
    for key in ("common", "nearby"):
        out[key] = [_location(x) for x in found[key] if _location(x)]
    return out


def _location(raw: dict[str, Any]) -> dict[str, Any] | None:
    try:
        return ItemLocation.model_validate(raw).model_dump()
    except ValueError:
        return None


# ---------------------------------------------------------------- 图片与 AI 文案
@router.post("/uploads")
async def upload(_: CurrentUser, file: UploadFile = File(...)) -> dict[str, str]:
    try:
        content = await read_limited(file, service.MAX_IMAGE_BYTES, "图片不能超过 10MB")
        image_id = service.save_upload(content, file.content_type or "")
    except ValueError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
    return {"id": image_id, "url": f"/api/v1/goods/uploads/{image_id}"}


class ImportImageUrlIn(BaseModel):
    url: str


# 只用于把选品雷达里的闲鱼商品图转存为草稿图片：限定阿里系图片域名，避免被用来访问内网（SSRF）
IMPORT_IMAGE_HOSTS = ("alicdn.com", "goofish.com", "taobao.com", "tbcdn.cn")


def _allowed_image_url(url: str) -> bool:
    try:
        u = httpx.URL(url)
    except httpx.InvalidURL:
        return False
    host = (u.host or "").lower()
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in IMPORT_IMAGE_HOSTS)


@router.post("/import-image-url")
async def import_image_url(body: ImportImageUrlIn, _: CurrentUser) -> dict[str, str]:
    """通过图片外链（例如选品雷达中的商品原图）转存为本地草稿图片。"""
    url = body.url.strip()
    if url.startswith("//"):
        url = "https:" + url
    elif url.startswith("http://"):
        url = "https://" + url[len("http://") :]
    if not _allowed_image_url(url):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "只支持导入闲鱼商品图片的链接")
    try:
        # 不跟随重定向：防止经由允许的域名跳转到内网地址
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            async with client.stream(
                "GET", url, headers={"User-Agent": "Mozilla/5.0", "Referer": "https://www.goofish.com/"}
            ) as resp:
                if resp.status_code != 200:
                    raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片下载失败，请稍后重试")
                buf = bytearray()
                async for chunk in resp.aiter_bytes():
                    buf += chunk
                    if len(buf) > service.MAX_IMAGE_BYTES:
                        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片不能超过 10MB")
    except httpx.HTTPError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片下载失败，请稍后重试") from e
    if not sniff_image(bytes(buf)):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "链接内容不是 JPG / PNG / WEBP 图片")
    image_id = service.save_upload(bytes(buf))
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
async def ai_copy(body: CopyIn, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
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
        view, _ = await with_fallback(
            session, user, None, lambda aid: service.market_for(out.search_keyword, None, aid)
        )
        result["market"] = view.model_dump()
    except GoofishError:
        result["market"] = None
    return result


# ---------------------------------------------------------------- 草稿与发布
@router.post("/ai-draft", response_model=DraftOut, status_code=201)
async def ai_draft(body: AiDraftIn, user: CurrentUser, session: SessionDep) -> PublishDraftRecord:
    """AI 根据图片（和可选的一句话说明）生成整份发布草稿，保存为待确认草稿，不会直接发布。"""
    await get_account_for(session, user, body.account_id)
    draft = None
    if body.draft_id is not None:
        draft = await session.get(PublishDraftRecord, body.draft_id)
        if draft is None or draft.account_id != body.account_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "草稿不存在")
        if draft.status in (DraftStatus.PUBLISHING, DraftStatus.PUBLISHED):
            raise HTTPException(status.HTTP_409_CONFLICT, "已发布的草稿不能重新生成")
    try:
        images = []
        for image_id in body.image_ids:
            data, media = service.load_upload(image_id)
            images.append((image_id, data, media))
    except FileNotFoundError as e:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "图片不存在，请重新上传") from e

    async def lookup(keyword: str):  # noqa: ANN202
        try:
            view, _ = await with_fallback(session, user, None, lambda aid: service.market_for(keyword, None, aid))
            return view
        except RiskBlockedError as e:
            raise RuntimeError("闲鱼风控保护中，暂停搜索") from e
        except GoofishError as e:
            raise RuntimeError(str(e)[:80]) from e

    try:
        out = await generate_listing(
            get_llm(), images=images, hint=body.hint, strategy=body.strategy, market_lookup=lookup
        )
    except LLMUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"大模型不可用：{e}") from e
    except LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"AI 生成失败：{e}") from e

    if draft is None:
        draft = PublishDraftRecord(account_id=body.account_id, created_by=user.id)
        session.add(draft)
    draft.title = out.title[:60]
    draft.desc = out.desc
    draft.image_ids = out.image_ids
    draft.price = out.price or 0
    draft.orig_price = out.orig_price
    draft.floor_price = out.floor_price
    draft.shipping = out.shipping
    draft.post_fee = out.post_fee
    draft.is_virtual = out.is_virtual
    draft.knowledge = out.knowledge
    draft.status = DraftStatus.DRAFT
    draft.scheduled_at = None
    draft.error = None
    draft.ai_meta = {**out.meta, "hint": body.hint}
    draft.confirmed_facts = []
    await session.commit()
    await record_audit(
        "goods.ai_draft",
        user_id=user.id,
        actor_type="ai",
        account_id=body.account_id,
        target_type="draft",
        target_id=draft.id,
        detail={"model": out.meta.get("model"), "price_source": out.meta.get("price_source")},
    )
    return draft


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
    if body.confirmed_facts:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "手动草稿没有 AI 待核验事项")
    if body.scheduled_at:
        try:
            service.validate_publish_draft(d)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
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
    if body.account_id != d.account_id:
        await get_account_for(session, user, body.account_id)  # 换发布账号：新账号也必须有权限
    if d.status in (DraftStatus.PUBLISHING, DraftStatus.PUBLISHED):
        raise HTTPException(status.HTTP_409_CONFLICT, "已发布的草稿不能修改")
    required = (d.ai_meta or {}).get("uncertain", [])
    if any(fact not in required for fact in body.confirmed_facts):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "核验事项已变化，请重新打开草稿确认")
    for k, v in body.model_dump().items():
        setattr(d, k, v)
    if body.scheduled_at:
        try:
            service.validate_publish_draft(d)
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, str(e)) from e
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
    if not d.price or d.price <= 0:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "请先在草稿里填写售价")
    if not d.title.strip() or not d.desc.strip() or not d.image_ids:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "草稿缺少标题、描述或图片")
    try:
        item_id = await service.publish_draft(draft_id, user.id)
    except ValueError as e:
        raise HTTPException(status.HTTP_409_CONFLICT, str(e)) from e
    except VerificationRequiredError as e:
        # 428：页面据此弹出认证二维码，认证后重新发布
        raise HTTPException(
            status.HTTP_428_PRECONDITION_REQUIRED, str(e), headers={"X-Verify-Url": e.verify_url}
        ) from e
    except GoofishError as e:
        raise goofish_http_error(e) from e
    return {"item_id": item_id, "published_at": datetime.now(UTC)}
