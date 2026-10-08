"""商品中心：同步、定价、AI 文案、草稿发布、擦亮。所有写操作经过网关风控并写审计。"""

import asyncio
import random
import uuid
from datetime import UTC, datetime
from pathlib import Path

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.events import Topics, bus
from app.domains.account.models import XyAccount
from app.domains.goods.models import DraftStatus, ItemStatus, MyItem, PublishDraftRecord
from app.domains.system.audit import record_audit
from app.goofish.dto import SearchQuery
from app.goofish.errors import GoofishError
from app.goofish.publish import PublishDraft, ShippingMode
from app.intelligence.llm import ImageInput, LLMGateway, Tier
from app.intelligence.pricing import PriceSuggestion, market_stats, suggest_price
from app.runtime import get_runtime

ALLOWED_IMAGE_TYPES = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp"}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


# ---------------------------------------------------------------- 本地图片
def uploads_dir() -> Path:
    d = get_settings().data_dir / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_upload(content: bytes, content_type: str) -> str:
    ext = ALLOWED_IMAGE_TYPES.get(content_type)
    if ext is None:
        raise ValueError("只支持 JPG / PNG / WEBP 图片")
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能超过 10MB")
    image_id = uuid.uuid4().hex + ext
    (uploads_dir() / image_id).write_bytes(content)
    return image_id


def load_upload(image_id: str) -> tuple[bytes, str]:
    if "/" in image_id or ".." in image_id:
        raise FileNotFoundError(image_id)
    path = uploads_dir() / image_id
    media = {v: k for k, v in ALLOWED_IMAGE_TYPES.items()}.get(path.suffix, "image/jpeg")
    return path.read_bytes(), media


# ---------------------------------------------------------------- 同步
async def sync_items(account_id: int, max_pages: int = 10) -> dict[str, int]:
    gateway = get_runtime().gateway
    async with session_factory()() as s:
        acc = await s.get(XyAccount, account_id)
        if acc is None:
            raise ValueError("账号不存在")
        unb = acc.unb
    rows: list[dict] = []
    for page in range(1, max_pages + 1):
        items, more = await gateway.list_my_items(account_id, unb, page)
        rows.extend(items)
        if not more:
            break
    created = updated = 0
    now = datetime.now(UTC)
    status_map = {"在售": ItemStatus.ON_SALE, "已售": ItemStatus.SOLD}
    async with session_factory()() as s:
        existing = {
            i.item_id: i for i in (await s.execute(select(MyItem).where(MyItem.account_id == account_id))).scalars()
        }
        seen = set()
        for row in rows:
            if not row["item_id"]:
                continue
            seen.add(row["item_id"])
            item = existing.get(row["item_id"])
            if item is None:
                item = MyItem(account_id=account_id, item_id=row["item_id"])
                s.add(item)
                created += 1
            else:
                updated += 1
            item.title = row["title"] or item.title
            item.price = row["price"] if row["price"] is not None else item.price
            item.image_url = row["image_url"] or item.image_url
            item.status = status_map.get(row["status"], ItemStatus.ON_SALE)
            item.synced_at = now
        for item_id, item in existing.items():
            if item_id not in seen and item.status == ItemStatus.ON_SALE:
                item.status = ItemStatus.OFFLINE
        await s.commit()
    return {"total": len(rows), "created": created, "updated": updated}


# ---------------------------------------------------------------- 定价
class MarketView(BaseModel):
    keyword: str
    sample: int
    suggestion: PriceSuggestion | None
    cheaper_competitors: list[dict]


async def market_for(keyword: str, my_price: float | None = None) -> MarketView:
    page = await get_runtime().gateway.search_items(SearchQuery(keyword=keyword, sort="default"))
    prices = [i.price for i in page.items]
    stats = market_stats(prices)
    cheaper = [
        {"title": i.title, "price": i.price, "link": i.link, "area": i.area}
        for i in sorted(page.items, key=lambda x: x.price or 0)
        if my_price and i.price and i.price < my_price
    ][:5]
    return MarketView(keyword=keyword, sample=stats.count, suggestion=suggest_price(stats), cheaper_competitors=cheaper)


# ---------------------------------------------------------------- AI 文案
class CopyOut(BaseModel):
    titles: list[str]
    desc: str
    search_keyword: str
    condition: str
    highlights: list[str]


COPY_SYSTEM = """你是闲鱼爆款文案助手。根据卖家上传的商品图片和补充说明写发布文案：
- titles：3 个标题，每个不超过 30 字，包含品牌型号和核心卖点，口吻像真实个人卖家，不要夸张营销词
- desc：150~300 字描述，依次说明 入手渠道/时间、成色与瑕疵（如实）、配件、出售原因、交易方式；
  不要承诺“保证正品”“假一赔十”，不要出现任何站外联系方式
- search_keyword：用于在闲鱼搜索同款比价的关键词（品牌+型号）
- condition：成色判断（全新/99新/95新/9成新/8成新及以下）
- highlights：3 个卖点短语
图片看不清的信息不要编造。"""


async def ai_copy(llm: LLMGateway, image_ids: list[str], hint: str) -> CopyOut:
    images = []
    for image_id in image_ids[:4]:
        data, media = load_upload(image_id)
        images.append(ImageInput(data=data, media_type=media))
    return await llm.complete_json(
        Tier.VISION,
        COPY_SYSTEM,
        f"卖家补充说明：{hint or '无'}",
        CopyOut,
        images=images,
        max_tokens=3000,
        effort="medium",
    )


# ---------------------------------------------------------------- 发布
async def publish_draft(draft_id: int, user_id: int | None = None) -> str:
    gateway = get_runtime().gateway
    async with session_factory()() as s:
        d = await s.get(PublishDraftRecord, draft_id)
        if d is None:
            raise ValueError("草稿不存在")
        if d.status in (DraftStatus.PUBLISHING, DraftStatus.PUBLISHED):
            raise ValueError("草稿已发布或正在发布")
        d.status = DraftStatus.PUBLISHING
        await s.commit()
        snapshot = {
            c: getattr(d, c)
            for c in (
                "account_id",
                "title",
                "desc",
                "image_ids",
                "price",
                "orig_price",
                "quantity",
                "shipping",
                "post_fee",
                "self_pickup",
                "floor_price",
                "knowledge",
                "is_virtual",
            )
        }
    account_id = snapshot["account_id"]
    try:
        uploaded = []
        for image_id in snapshot["image_ids"]:
            data, _ = load_upload(image_id)
            uploaded.append(await gateway.upload_image(account_id, data, image_id))
        payload = PublishDraft(
            title=snapshot["title"],
            desc=snapshot["desc"],
            images=uploaded,
            price=snapshot["price"],
            orig_price=snapshot["orig_price"],
            quantity=snapshot["quantity"],
            shipping=ShippingMode(snapshot["shipping"]),
            post_fee=snapshot["post_fee"],
            self_pickup=snapshot["self_pickup"],
        )
        item_id = await gateway.publish_item(account_id, payload)
    except (GoofishError, ValueError, FileNotFoundError) as e:
        async with session_factory()() as s:
            d = await s.get(PublishDraftRecord, draft_id)
            d.status, d.error = DraftStatus.FAILED, str(e)[:500]
            await s.commit()
        await record_audit(
            "goods.publish",
            user_id=user_id,
            account_id=account_id,
            target_type="draft",
            target_id=draft_id,
            success=False,
            error=str(e)[:500],
        )
        raise
    async with session_factory()() as s:
        d = await s.get(PublishDraftRecord, draft_id)
        d.status, d.item_id, d.error = DraftStatus.PUBLISHED, item_id, None
        s.add(
            MyItem(
                account_id=account_id,
                item_id=item_id,
                title=snapshot["title"],
                price=snapshot["price"],
                desc=snapshot["desc"],
                floor_price=snapshot["floor_price"],
                knowledge=snapshot["knowledge"],
                is_virtual=snapshot["is_virtual"],
                status=ItemStatus.ON_SALE,
                synced_at=datetime.now(UTC),
            )
        )
        await s.commit()
    await record_audit(
        "goods.publish",
        user_id=user_id,
        actor_type="human" if user_id else "system",
        account_id=account_id,
        target_type="item",
        target_id=item_id,
        detail={"draft_id": draft_id, "title": snapshot["title"]},
    )
    await bus.publish(Topics.ITEM_PUBLISHED, {"account_id": account_id, "item_id": item_id})
    return item_id


async def publish_due_drafts() -> None:
    now = datetime.now(UTC)
    async with session_factory()() as s:
        due = [
            d.id
            for d in (
                await s.execute(select(PublishDraftRecord).where(PublishDraftRecord.status == DraftStatus.SCHEDULED))
            ).scalars()
            if d.scheduled_at
            and (d.scheduled_at if d.scheduled_at.tzinfo else d.scheduled_at.replace(tzinfo=UTC)) <= now
        ]
    for draft_id in due:
        try:
            await publish_draft(draft_id)
        except Exception as e:  # noqa: BLE001
            logger.warning("定时发布失败 draft={} err={}", draft_id, e)


# ---------------------------------------------------------------- 擦亮
async def polish_item(item: MyItem, user_id: int | None = None) -> None:
    await get_runtime().gateway.polish_item(item.account_id, item.item_id)
    async with session_factory()() as s:
        row = await s.get(MyItem, item.id)
        if row:
            row.last_polished_at = datetime.now(UTC)
            await s.commit()
    await record_audit(
        "goods.polish",
        user_id=user_id,
        actor_type="human" if user_id else "rule",
        account_id=item.account_id,
        target_type="item",
        target_id=item.item_id,
    )


async def polish_all() -> None:
    """每日擦亮：只处理开启了 auto_polish 的账号，商品之间随机间隔。"""
    async with session_factory()() as s:
        accounts = [a for a in (await s.execute(select(XyAccount))).scalars() if a.get_settings().auto_polish]
        items = []
        for acc in accounts:
            items += list(
                (
                    await s.execute(
                        select(MyItem).where(MyItem.account_id == acc.id, MyItem.status == ItemStatus.ON_SALE)
                    )
                ).scalars()
            )
    for item in items:
        try:
            await polish_item(item)
        except GoofishError as e:
            logger.warning("擦亮失败 item={} err={}", item.item_id, e)
        await asyncio.sleep(random.uniform(20, 60))
