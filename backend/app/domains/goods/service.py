"""商品中心：同步、定价、AI 文案、草稿发布、擦亮。所有写操作经过网关风控并写审计。"""

import asyncio
import random
import time
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from loguru import logger
from pydantic import BaseModel
from sqlalchemy import func, select, update
from sqlalchemy.exc import SQLAlchemyError

from app.core.config import get_settings
from app.core.db import session_factory
from app.core.events import Topics, bus
from app.core.uploads import sniff_image
from app.domains.account.models import XyAccount
from app.domains.goods.models import DraftStatus, ItemStatus, MyItem, PublishDraftRecord
from app.domains.order.models import CardBinding, CardPool
from app.domains.system.audit import record_audit
from app.goofish.dto import SearchQuery
from app.goofish.errors import GoofishError, NetworkError, RiskBlockedError, RiskControlError
from app.goofish.gateway import MULTI_INVENTORY_HINT
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


def save_upload(content: bytes, content_type: str = "") -> str:
    """content_type 仅作参考：真实格式按文件头判断，伪装成图片的 HTML / SVG 等一律拒绝。"""
    if len(content) > MAX_IMAGE_BYTES:
        raise ValueError("图片不能超过 10MB")
    ext = ALLOWED_IMAGE_TYPES.get(sniff_image(content) or "")
    if ext is None:
        raise ValueError("只支持 JPG / PNG / WEBP 图片")
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
    stats = await refresh_listing_stats(account_id)
    return {"total": len(rows), "created": created, "updated": updated, "stats": stats}


STATS_PER_SYNC = 10  # 每次同步最多补全的商品数：详情接口受风控限速，分多次同步逐步补全


async def refresh_listing_stats(account_id: int, limit: int = STATS_PER_SYNC) -> int:
    """按“最久没更新”优先，从商品详情补全想要数、浏览量和发布时间。遇到风控立即停止。"""
    gateway = get_runtime().gateway
    async with session_factory()() as s:
        targets = [
            i.item_id
            for i in (
                await s.execute(
                    select(MyItem)
                    .where(MyItem.account_id == account_id, MyItem.status == ItemStatus.ON_SALE)
                    .order_by(MyItem.stats_at.is_not(None), MyItem.stats_at)
                    .limit(limit)
                )
            ).scalars()
        ]
    done = 0
    for item_id in targets:
        try:
            detail = await gateway.get_item_detail(item_id, account_id)
        except (RiskBlockedError, RiskControlError):
            logger.warning("补全商品数据时触发风控，本次停止 account={}", account_id)
            break
        except GoofishError as e:
            logger.info("补全商品数据失败 item={}：{}", item_id, e)
            continue
        async with session_factory()() as s:
            item = (
                await s.execute(select(MyItem).where(MyItem.account_id == account_id, MyItem.item_id == item_id))
            ).scalar_one_or_none()
            if item is None:
                continue
            d = detail.item
            item.want_cnt = d.want_cnt if d.want_cnt is not None else item.want_cnt
            item.browse_cnt = d.browse_cnt if d.browse_cnt is not None else item.browse_cnt
            item.publish_time = d.publish_time or item.publish_time
            item.stats_at = datetime.now(UTC)
            await s.commit()
        done += 1
    return done


# ---------------------------------------------------------------- 定价
class MarketView(BaseModel):
    keyword: str
    sample: int
    suggestion: PriceSuggestion | None
    cheaper_competitors: list[dict]


MARKET_CACHE_TTL = 600  # 秒：同一关键词 10 分钟内复用搜索结果，节省搜索配额
_market_cache: dict[str, tuple[float, list]] = {}


async def _market_items(keyword: str, account_id: int | None = None) -> list:
    key = keyword.strip().lower()
    now = time.monotonic()
    hit = _market_cache.get(key)
    if hit and now - hit[0] < MARKET_CACHE_TTL:
        return hit[1]
    page = await get_runtime().gateway.search_items(SearchQuery(keyword=keyword, sort="default"), account_id)
    _market_cache[key] = (now, page.items)
    if len(_market_cache) > 500:  # 简单的容量控制
        for k in sorted(_market_cache, key=lambda k: _market_cache[k][0])[:100]:
            _market_cache.pop(k, None)
    return page.items


async def market_for(keyword: str, my_price: float | None = None, account_id: int | None = None) -> MarketView:
    items = await _market_items(keyword, account_id)
    prices = [i.price for i in items]
    stats = market_stats(prices)
    cheaper = [
        {"title": i.title, "price": i.price, "link": i.link, "area": i.area}
        for i in sorted(items, key=lambda x: x.price or 0)
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
UNCERTAIN_PUBLISH_HINT = (
    "发布请求已发出但没有收到闲鱼的结果，可能已经上架：请先到闲鱼 App「我发布的」核对，确认没有再重试"
)


def validate_publish_draft(draft: PublishDraftRecord) -> None:
    """所有发布入口共用检查；草稿可以保存不完整内容，但不能发布未核验事实。"""
    if not draft.title.strip() or not draft.desc.strip() or not draft.image_ids:
        raise ValueError("草稿缺少标题、描述或图片，请补全后发布")
    if not draft.price or draft.price <= 0:
        raise ValueError("请先填写有效售价后发布")
    if draft.floor_price is not None and draft.floor_price > draft.price:
        raise ValueError("底价不能高于售价")
    pending = [fact for fact in (draft.ai_meta or {}).get("uncertain", []) if fact not in (draft.confirmed_facts or [])]
    if pending:
        raise ValueError(f"还有 {len(pending)} 项商品信息未核验：{'；'.join(pending)}。请在确认页核验后发布")


async def publish_draft(draft_id: int, user_id: int | None = None) -> str:
    gateway = get_runtime().gateway
    async with session_factory()() as s:
        # 原子领取：只有把状态从「未发布」改成「发布中」成功的那一方继续，
        # 定时任务与手动发布、或多个进程同时处理同一草稿时不会重复上架
        claimed = await s.execute(
            update(PublishDraftRecord)
            .where(
                PublishDraftRecord.id == draft_id,
                PublishDraftRecord.status.not_in([DraftStatus.PUBLISHING, DraftStatus.PUBLISHED, DraftStatus.UNKNOWN]),
            )
            .values(status=DraftStatus.PUBLISHING)
        )
        await s.commit()
        d = await s.get(PublishDraftRecord, draft_id)
        if d is None:
            raise ValueError("草稿不存在")
        if claimed.rowcount != 1:
            if d.status == DraftStatus.UNKNOWN:
                raise ValueError(UNCERTAIN_PUBLISH_HINT)
            raise ValueError("草稿已发布或正在发布")
        try:
            validate_publish_draft(d)
        except ValueError as e:
            d.status, d.error = DraftStatus.FAILED, str(e)
            await s.commit()
            raise
        if not await _creator_can_use(s, d):
            # 定时发布不经过接口鉴权：再确认一次创建者仍有该账号的权限（授权可能已被收回）
            d.status, d.error = DraftStatus.FAILED, "草稿创建者已无权使用该闲鱼账号"
            await s.commit()
            raise ValueError(d.error)
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
                "location",
            )
        }
        location = snapshot["location"]
        if location is None:  # 沿用账号上次使用的所在地
            acc = await s.get(XyAccount, snapshot["account_id"])
            location = (acc.settings or {}).get("publish_location") if acc else None
    account_id = snapshot["account_id"]
    request_sent = False
    try:
        if snapshot["quantity"] > 1:
            # 先确认账号能否发多库存，免得上传完图片才被闲鱼拒绝
            cap = await gateway.publish_capability(account_id)
            if not cap["support_inventory"]:
                raise ValueError(MULTI_INVENTORY_HINT)
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
        request_sent = True
        item_id = await gateway.publish_item(account_id, payload, location)
    except Exception as e:
        # 发布请求已发出却没拿到结果（网络中断、超时等）：闲鱼那边可能已经上架，提示先核对，别直接重试
        uncertain = request_sent and (isinstance(e, NetworkError) or not isinstance(e, GoofishError | ValueError))
        error = (f"{UNCERTAIN_PUBLISH_HINT}（{e or type(e).__name__}）" if uncertain else str(e))[:500]
        async with session_factory()() as s:
            d = await s.get(PublishDraftRecord, draft_id)
            if d:
                d.status, d.error = DraftStatus.UNKNOWN if uncertain else DraftStatus.FAILED, error
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
        if location:  # 记住本次所在地，下次发布默认沿用
            acc = await s.get(XyAccount, account_id)
            if acc is not None:
                acc.settings = {**(acc.settings or {}), "publish_location": location}
                d.location = location
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
    await setup_draft_delivery(draft_id)
    return item_id


async def setup_draft_delivery(draft_id: int) -> dict | None:
    """仅修复本地发货关联，绝不再次请求闲鱼发布；结果持久化供刷新和定时发布查看。"""
    try:
        async with session_factory()() as session:
            # 先取得数据库写锁，串行处理重复点击，SQLite 与 PostgreSQL 均避免重复关联。
            await session.execute(update(PublishDraftRecord).where(PublishDraftRecord.id == draft_id).values(updated_at=datetime.now(UTC)))
            draft = await session.get(PublishDraftRecord, draft_id)
            if draft is None:
                raise ValueError("草稿不存在")
            if not draft.delivery_setup:
                return None
            if draft.status != DraftStatus.PUBLISHED or not draft.item_id:
                raise ValueError("商品尚未确认发布成功，不能关联发货")
            if not await _creator_can_use(session, draft):
                raise ValueError("草稿创建者已无权使用该闲鱼账号")
            setup = draft.delivery_setup
            pool = await session.get(CardPool, setup["pool_id"])
            if pool is None or pool.owner_id != draft.created_by:
                raise ValueError("发货内容已删除或创建者无权使用，请在商品管理中重新关联")
            if not pool.enabled:
                raise ValueError("发货内容已停用，请先在自动发货页面启用后重试关联")
            existing = (await session.execute(select(CardBinding).where(
                CardBinding.owner_id == draft.created_by,
                CardBinding.account_id == draft.account_id,
                CardBinding.item_id == draft.item_id,
                CardBinding.spec_value.is_(None),
            ))).scalars().all()
            if existing and any(binding.pool_id != pool.id for binding in existing):
                raise ValueError("商品已关联其他发货内容，请到商品管理核对，未覆盖原关联")
            if not existing:
                session.add(CardBinding(
                    owner_id=draft.created_by, pool_id=pool.id, account_id=draft.account_id,
                    item_id=draft.item_id, template="您购买的内容如下：\n{content}\n祝您使用愉快！",
                    delay_seconds=0, max_per_buyer=1, auto_relist=setup["auto_relist"],
                ))
            draft.delivery_setup = {**setup, "status": "linked", "error": None}
            await session.commit()
            return draft.delivery_setup
    except (ValueError, SQLAlchemyError) as error:
        logger.warning("发货关联失败 draft={} err={}", draft_id, error)
        async with session_factory()() as session:
            draft = await session.get(PublishDraftRecord, draft_id)
            if draft is None or not draft.delivery_setup:
                raise
            draft.delivery_setup = {**draft.delivery_setup, "status": "error", "error": str(error)}
            await session.commit()
            return draft.delivery_setup


async def _creator_can_use(s, d: PublishDraftRecord) -> bool:  # noqa: ANN001
    from app.domains.account.service import accessible_account_ids
    from app.domains.system.models import User

    if d.created_by is None:
        return True
    user = await s.get(User, d.created_by)
    if user is None or not user.is_active:
        return False
    allowed = await accessible_account_ids(s, user)
    return allowed is None or d.account_id in allowed


async def publish_due_drafts() -> None:
    now = datetime.now(UTC)
    async with session_factory()() as s:
        # 自愈：卡在 publishing 超过 10 分钟未完成的草稿（如进程意外中断）重置为失败
        stale_threshold = now - timedelta(minutes=10)
        stale = (
            await s.execute(
                select(PublishDraftRecord).where(
                    PublishDraftRecord.status == DraftStatus.PUBLISHING,
                    PublishDraftRecord.updated_at <= stale_threshold,
                )
            )
        ).scalars()
        for d in stale:
            d.status, d.error = DraftStatus.UNKNOWN, UNCERTAIN_PUBLISH_HINT
        await s.commit()

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


async def polish_all(account_id: int | None = None, only_accounts: list[int] | None = None) -> int:
    """每日擦亮：只处理开启了 auto_polish 的账号（若指定 account_id 则对该账号在售商品执行），商品之间随机间隔。
    only_accounts：手动触发时限定为发起人有权限的账号。"""
    async with session_factory()() as s:
        stmt = select(XyAccount)
        if account_id:
            stmt = stmt.where(XyAccount.id == account_id)
        else:
            stmt = stmt.where(XyAccount.status == "active")
        if only_accounts is not None:
            stmt = stmt.where(XyAccount.id.in_(only_accounts))
        accounts = [a for a in (await s.execute(stmt)).scalars() if account_id or a.get_settings().auto_polish]
        items = []
        for acc in accounts:
            items += list(
                (
                    await s.execute(
                        select(MyItem).where(MyItem.account_id == acc.id, MyItem.status == ItemStatus.ON_SALE)
                    )
                ).scalars()
            )
    count = 0
    for item in items:
        try:
            await polish_item(item)
            count += 1
        except GoofishError as e:
            logger.warning("擦亮失败 item={} err={}", item.item_id, e)
        await asyncio.sleep(random.uniform(5, 15))
    return count


# ---------------------------------------------------------------- 卖完自动重新上架
# 网页版对多数个人账号不开放库存（只能发 1 件），电子资料卖出一件就下架。
# 关联了发货内容并开启「卖完自动重新上架」的商品：卖完后用原商品的标题、描述、图片、价格发布一件新的，
# 发货关联、底价和知识库一并转到新商品上，后续订单照常自动发货。
_relist_locks: dict[tuple[int, str], asyncio.Lock] = {}
RELIST_MAX_IMAGES = 9


async def _download_image(url: str) -> bytes:
    import httpx

    if url.startswith("//"):
        url = "https:" + url
    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
        resp = await http.get(url)
    resp.raise_for_status()
    return resp.content


async def relist_sold_item(account_id: int, item_id: str) -> str | None:
    """原商品已卖完下架时发布一件同样的新商品，返回新商品 ID；仍在售（多库存）或已处理过时返回 None。"""
    from app.domains.buyer.watch import ended_reason
    from app.domains.order.models import CardBinding, CardItem, CardPool

    lock = _relist_locks.setdefault((account_id, item_id), asyncio.Lock())
    async with lock:  # 同一商品并发的多个订单只重新上架一次
        async with session_factory()() as s:
            bindings = list(
                (
                    await s.execute(
                        select(CardBinding).where(
                            CardBinding.item_id == item_id,
                            CardBinding.auto_relist.is_(True),
                            (CardBinding.account_id == account_id) | CardBinding.account_id.is_(None),
                        )
                    )
                ).scalars()
            )
            if not bindings:
                return None
            # 发货内容已经发完：上架了也发不出货，不重新上架
            pool = await s.get(CardPool, bindings[0].pool_id)
            if pool is None or not pool.enabled:
                return None
            if pool.kind == "pool":
                left = (
                    await s.execute(
                        select(func.count())
                        .select_from(CardItem)
                        .where(CardItem.pool_id == pool.id, CardItem.status == "available")
                    )
                ).scalar_one()
                if left == 0:
                    logger.info("商品 {} 的卡密已用完，不自动重新上架", item_id)
                    return None
            old = (
                await s.execute(select(MyItem).where(MyItem.account_id == account_id, MyItem.item_id == item_id))
            ).scalar_one_or_none()
            acc = await s.get(XyAccount, account_id)
            location = (acc.settings or {}).get("publish_location") if acc else None
            owner_id = acc.owner_id if acc else None

        gateway = get_runtime().gateway
        detail = await gateway.get_item_detail(item_id, account_id)
        if not ended_reason(detail):
            return None  # 还在售（如在 App 里设了库存），不需要重新上架
        src = detail.item
        uploaded = []
        for i, url in enumerate((src.images or [src.image_url])[:RELIST_MAX_IMAGES]):
            if url:
                uploaded.append(await gateway.upload_image(account_id, await _download_image(url), f"relist_{i}.jpg"))
        if not uploaded:
            raise GoofishError("原商品没有可用的图片，无法重新上架")
        title = (src.title or src.desc or (old.title if old else "")).strip()[:60]
        draft = PublishDraft(
            title=title,
            desc=(src.desc or title).strip()[:5000],
            images=uploaded,
            price=src.price or (old.price if old else 0) or 0,
            orig_price=src.orig_price,
            quantity=1,
            shipping=ShippingMode.NO_SHIPPING,  # 关联了发货内容的都是虚拟商品
        )
        new_id = await gateway.publish_item(account_id, draft, location)

        async with session_factory()() as s:
            s.add(
                MyItem(
                    account_id=account_id,
                    item_id=new_id,
                    title=title,
                    price=draft.price,
                    image_url=uploaded[0].url,
                    status=ItemStatus.ON_SALE,
                    desc=draft.desc,
                    floor_price=old.floor_price if old else None,
                    knowledge=old.knowledge if old else "",
                    is_virtual=True,
                )
            )
            # 发货关联转到新商品；旧商品已下架，关掉它的自动重新上架，避免重复发布
            for b in bindings:
                row = await s.get(CardBinding, b.id)
                if row is None:
                    continue
                s.add(
                    CardBinding(
                        owner_id=row.owner_id,
                        pool_id=row.pool_id,
                        account_id=row.account_id,
                        item_id=new_id,
                        spec_value=row.spec_value,
                        template=row.template,
                        delay_seconds=row.delay_seconds,
                        max_per_buyer=row.max_per_buyer,
                        auto_relist=True,
                    )
                )
                row.auto_relist = False
            await s.commit()

    await record_audit(
        "goods.relist",
        actor_type="rule",
        account_id=account_id,
        target_type="item",
        target_id=new_id,
        detail={"from_item": item_id},
    )
    from app.notify.senders import Notification
    from app.notify.service import NotifyEvents, notify_background

    notify_background(
        owner_id,
        Notification(
            event=NotifyEvents.ITEM_RELISTED,
            title=f"🔁 「{title}」卖完已自动重新上架",
            content=f"原商品 {item_id} 已卖完下架，已发布同样的新商品 {new_id}，自动发货关联已转到新商品。",
            url=f"https://www.goofish.com/item?id={new_id}",
        ),
    )
    logger.info("商品 {} 卖完，已自动重新上架为 {}", item_id, new_id)
    return new_id
