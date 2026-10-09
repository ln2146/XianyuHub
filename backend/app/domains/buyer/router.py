import asyncio
import csv
import io
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta
from typing import Any

from croniter import croniter
from fastapi import APIRouter, HTTPException, Query, Response, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field, field_validator
from sqlalchemy import func, select

from app.core.deps import CurrentUser, SessionDep
from app.core.events import Topics, bus
from app.core.pagination import set_total
from app.domains.account.service import get_account_for
from app.domains.buyer import scheduling
from app.domains.buyer.ai import draft_task
from app.domains.buyer.analysis import (
    InsightOut,
    ItemAnalysis,
    PricePoint,
    SellerAnalysis,
    ai_insight,
    analyze_item,
    analyze_seller,
)
from app.domains.buyer.models import (
    MarketItemRecord,
    MonitorTask,
    PriceSnapshot,
    SellerProfileCache,
    TaskResult,
    UserMark,
    Verdict,
)
from app.domains.buyer.pipeline import load_seller_profile, run_task, task_lock, upsert_market_item
from app.goofish.dto import ItemDetail, SearchQuery
from app.goofish.errors import GoofishError, RiskBlockedError, RiskControlError
from app.intelligence.llm import LLMError, LLMUnavailable, get_llm
from app.intelligence.pricing import deal_label, market_stats
from app.intelligence.rules import ItemRules
from app.runtime import get_runtime

router = APIRouter(prefix="/buyer", tags=["buyer"])
_background: set[asyncio.Task] = set()


class TaskIn(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    keywords: list[str] = Field(min_length=1, max_length=8)
    min_price: float | None = None
    max_price: float | None = None
    province: str | None = None
    city: str | None = None
    publish_days: int | None = Field(default=None, ge=1, le=30)
    personal_only: bool = False
    free_shipping: bool = False
    sort: str = "newest"
    max_pages: int = Field(default=1, ge=1, le=5)
    rules: ItemRules = Field(default_factory=ItemRules)
    criteria: str = ""
    decision_mode: str = Field(default="ai", pattern="^(ai|rule)$")
    analyze_images: bool = True
    ai_prescreen: bool = True
    fetch_seller_profile: bool = False
    notify_conditional: bool = False
    price_drop_percent: float = Field(default=5, ge=0, le=90)
    account_id: int | None = None
    cron: str = "*/30 8-23 * * *"
    enabled: bool = True

    @field_validator("cron")
    @classmethod
    def _cron(cls, v: str) -> str:
        if not croniter.is_valid(v):
            raise ValueError("cron 表达式无效")
        fields = v.split()
        if fields[0] in ("*", "*/1", "*/2", "*/3", "*/4"):
            raise ValueError("执行频率过高（间隔至少 5 分钟），容易触发风控")
        return v


class TaskOut(TaskIn):
    id: int
    last_run_at: datetime | None
    last_status: str | None
    last_error: str | None
    last_stats: dict[str, Any]
    paused_reason: str | None
    running: bool = False
    result_counts: dict[str, int] = Field(default_factory=dict)


class GenerateIn(BaseModel):
    description: str = Field(min_length=4, max_length=2000)


class ResultOut(BaseModel):
    id: int
    task_id: int
    item_id: str
    stage: str
    verdict: str | None
    confidence: float | None
    reason: str
    filter_reasons: list[str]
    risk_tags: list[str]
    need_confirm: list[str]
    questions: list[str]
    seller_type: str | None
    deal_score: int | None
    deal_label: str
    mark: str
    created_at: datetime
    item: dict[str, Any]


class MarkIn(BaseModel):
    mark: UserMark


async def _own_task(session, user, task_id: int) -> MonitorTask:
    task = await session.get(MonitorTask, task_id)
    if task is None or (task.owner_id != user.id and user.role != "admin"):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "任务不存在")
    return task


def _task_out(t: MonitorTask, counts: dict[str, int] | None = None) -> TaskOut:
    data = {c: getattr(t, c) for c in TaskIn.model_fields}
    data["rules"] = ItemRules.model_validate(t.rules or {})
    return TaskOut(
        **data,
        id=t.id,
        last_run_at=t.last_run_at,
        last_status=t.last_status,
        last_error=t.last_error,
        last_stats=t.last_stats or {},
        paused_reason=t.paused_reason,
        running=task_lock(t.id).locked(),
        result_counts=counts or {},
    )


@router.get("/tasks", response_model=list[TaskOut])
async def list_tasks(user: CurrentUser, session: SessionDep) -> list[TaskOut]:
    tasks = list(
        (
            await session.execute(select(MonitorTask).where(MonitorTask.owner_id == user.id).order_by(MonitorTask.id))
        ).scalars()
    )
    counts: dict[int, dict[str, int]] = {}
    if tasks:
        rows = await session.execute(
            select(TaskResult.task_id, TaskResult.verdict, func.count())
            .where(TaskResult.task_id.in_([t.id for t in tasks]))
            .group_by(TaskResult.task_id, TaskResult.verdict)
        )
        for task_id, verdict, n in rows:
            counts.setdefault(task_id, {})[verdict or "filtered"] = n
    return [_task_out(t, counts.get(t.id)) for t in tasks]


@router.post("/tasks", response_model=TaskOut, status_code=201)
async def create_task(body: TaskIn, user: CurrentUser, session: SessionDep) -> TaskOut:
    data = body.model_dump()
    data["rules"] = body.rules.model_dump()
    task = MonitorTask(owner_id=user.id, **data)
    session.add(task)
    await session.commit()
    scheduling.sync_task(task)
    await bus.publish(Topics.BUYER_TASK_CHANGED, {"task_id": task.id})
    return _task_out(task)


@router.post("/tasks/generate")
async def generate_task(body: GenerateIn, _: CurrentUser) -> dict[str, Any]:
    llm = get_llm()
    try:
        draft = await draft_task(llm, body.description)
    except LLMUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"大模型不可用：{e}") from e
    except LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return {
        "name": draft.name,
        "keywords": draft.keywords,
        "min_price": draft.min_price,
        "max_price": draft.max_price,
        "province": draft.province,
        "city": draft.city,
        "publish_days": draft.publish_days,
        "personal_only": draft.personal_only,
        "rules": {"include_all": draft.include_all, "exclude": draft.exclude},
        "criteria": draft.criteria,
    }


@router.get("/tasks/{task_id}", response_model=TaskOut)
async def get_task(task_id: int, user: CurrentUser, session: SessionDep) -> TaskOut:
    return _task_out(await _own_task(session, user, task_id))


@router.put("/tasks/{task_id}", response_model=TaskOut)
async def update_task(task_id: int, body: TaskIn, user: CurrentUser, session: SessionDep) -> TaskOut:
    task = await _own_task(session, user, task_id)
    for k, v in body.model_dump().items():
        setattr(task, k, v)
    task.rules = body.rules.model_dump()
    task.paused_reason = None
    task.consecutive_failures = 0
    await session.commit()
    scheduling.sync_task(task)
    await bus.publish(Topics.BUYER_TASK_CHANGED, {"task_id": task.id})
    return _task_out(task)


@router.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, user: CurrentUser, session: SessionDep) -> None:
    task = await _own_task(session, user, task_id)
    scheduling.remove_task(task.id)
    await session.delete(task)
    await session.commit()
    await bus.publish(Topics.BUYER_TASK_CHANGED, {"task_id": task_id})


@router.post("/tasks/{task_id}/run", status_code=202)
async def trigger_task(task_id: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    task = await _own_task(session, user, task_id)
    if task_lock(task.id).locked():
        raise HTTPException(status.HTTP_409_CONFLICT, "任务正在运行")
    if task.paused_reason:
        task.paused_reason = None
        task.consecutive_failures = 0
        await session.commit()
    bg = asyncio.create_task(run_task(task.id))
    _background.add(bg)
    bg.add_done_callback(_background.discard)
    return {"started": True}


@router.get("/results", response_model=list[ResultOut])
async def list_results(
    user: CurrentUser,
    session: SessionDep,
    task_id: int | None = None,
    verdict: str | None = Query(None, description="recommend/conditional/reject/filtered/all"),
    mark: str | None = None,
    q: str | None = None,
    sort: str = Query("newest", pattern="^(newest|price_asc|deal)$"),
    limit: int = Query(50, le=200),
    offset: int = 0,
    response: Response = None,  # type: ignore[assignment]  # 直接调用（导出 CSV）时可不传
) -> list[ResultOut]:
    stmt = (
        select(TaskResult, MarketItemRecord)
        .join(MarketItemRecord, MarketItemRecord.item_id == TaskResult.item_id)
        .join(MonitorTask, MonitorTask.id == TaskResult.task_id)
        .where(MonitorTask.owner_id == user.id)
    )
    if task_id is not None:
        stmt = stmt.where(TaskResult.task_id == task_id)
    if verdict in (None, "", "default"):
        stmt = stmt.where(TaskResult.verdict.in_([Verdict.RECOMMEND, Verdict.CONDITIONAL]))
    elif verdict == "filtered":
        stmt = stmt.where(TaskResult.verdict.is_(None))
    elif verdict != "all":
        stmt = stmt.where(TaskResult.verdict == verdict)
    if mark:
        stmt = stmt.where(TaskResult.mark == mark)
    else:
        stmt = stmt.where(TaskResult.mark != UserMark.IGNORED)
    if q:
        stmt = stmt.where(MarketItemRecord.title.contains(q))
    order = {
        "newest": TaskResult.id.desc(),
        "price_asc": MarketItemRecord.price.asc(),
        "deal": TaskResult.deal_score.desc(),
    }[sort]
    await set_total(response, session, stmt)
    rows = (await session.execute(stmt.order_by(order).limit(limit).offset(offset))).all()
    return [
        ResultOut(
            id=r.id,
            task_id=r.task_id,
            item_id=r.item_id,
            stage=r.stage,
            verdict=r.verdict,
            confidence=r.confidence,
            reason=r.reason,
            filter_reasons=r.filter_reasons or [],
            risk_tags=r.risk_tags or [],
            need_confirm=r.need_confirm or [],
            questions=r.questions or [],
            seller_type=r.seller_type,
            deal_score=r.deal_score,
            deal_label=deal_label(r.deal_score),
            mark=r.mark,
            created_at=r.created_at,
            item={
                "title": m.title,
                "price": m.price,
                "orig_price": m.orig_price,
                "area": m.area,
                "image_url": m.image_url,
                "link": m.link,
                "want_cnt": m.want_cnt,
                "browse_cnt": m.browse_cnt,
                "seller_nick": m.seller_nick,
                "seller_id": m.seller_id,
                "seller_zhima": m.seller_zhima,
                "publish_time": m.publish_time,
                "tags": m.tags or [],
            },
        )
        for r, m in rows
    ]


@router.patch("/results/{result_id}")
async def mark_result(result_id: int, body: MarkIn, user: CurrentUser, session: SessionDep) -> dict[str, str]:
    res = await session.get(TaskResult, result_id)
    if res is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "结果不存在")
    await _own_task(session, user, res.task_id)
    res.mark = body.mark
    await session.commit()
    return {"mark": res.mark}


@router.get("/results/export.csv")
async def export_results(user: CurrentUser, session: SessionDep, task_id: int | None = None) -> StreamingResponse:
    rows = await list_results(
        user, session, task_id=task_id, verdict="all", mark=None, q=None, sort="newest", limit=200, offset=0
    )
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf)
    w.writerow(["结论", "标题", "价格", "地区", "性价比", "理由", "风险", "需确认", "链接"])
    for r in rows:
        w.writerow(
            [
                r.verdict or "筛除",
                r.item["title"],
                r.item["price"],
                r.item["area"],
                r.deal_label,
                r.reason or "；".join(r.filter_reasons),
                "、".join(r.risk_tags),
                "、".join(r.need_confirm),
                r.item["link"],
            ]
        )
    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": 'attachment; filename="results.csv"'},
    )


@router.get("/items/{item_id}/prices")
async def price_history(item_id: str, _: CurrentUser, session: SessionDep) -> list[dict[str, Any]]:
    rows = await session.execute(
        select(PriceSnapshot).where(PriceSnapshot.item_id == item_id).order_by(PriceSnapshot.seen_at)
    )
    return [{"price": p.price, "seen_at": p.seen_at} for p in rows.scalars()]


@router.get("/tasks/{task_id}/market")
async def task_market(task_id: int, user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    await _own_task(session, user, task_id)
    rows = await session.execute(
        select(MarketItemRecord.price)
        .join(TaskResult, TaskResult.item_id == MarketItemRecord.item_id)
        .where(TaskResult.task_id == task_id)
    )
    return market_stats([r[0] for r in rows]).model_dump()


# ---------------------------------------------------------------- 实时搜索与详情
@contextmanager
def _goofish_errors(action: str) -> Iterator[None]:
    try:
        yield
    except RiskBlockedError as e:
        raise HTTPException(status.HTTP_423_LOCKED, f"账号保护中：{e}") from e
    except RiskControlError as e:
        raise HTTPException(status.HTTP_429_TOO_MANY_REQUESTS, f"触发闲鱼安全限制：{e}") from e
    except GoofishError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"{action}失败：{e}") from e


async def _save_detail(session, detail: ItemDetail) -> MarketItemRecord:  # noqa: ANN001
    rec, _ = await upsert_market_item(session, detail.item)
    rec.seller_zhima = detail.seller.zhima_level or rec.seller_zhima
    if detail.seller.reg_days is not None:
        rec.seller_reg_days = detail.seller.reg_days
    rec.detail_fetched_at = datetime.now(UTC)
    await session.commit()
    return rec


@router.get("/search")
async def live_search(
    user: CurrentUser,
    session: SessionDep,
    keyword: str = Query(min_length=1, max_length=100),
    page: int = Query(default=1, ge=1, le=50),
    sort: str = Query(default="newest", pattern="^(newest|price_asc|price_desc|default)$"),
    min_price: int | None = Query(default=None, ge=0),
    max_price: int | None = Query(default=None, ge=0),
    province: str | None = None,
    city: str | None = None,
    publish_days: int | None = Query(default=None, ge=1, le=30),
    personal_only: bool = False,
    free_shipping: bool = False,
    account_id: int | None = None,
) -> dict[str, Any]:
    if account_id is not None:
        await get_account_for(session, user, account_id)
    query = SearchQuery(
        keyword=keyword.strip(),
        page=page,
        sort=sort,
        min_price=min_price,
        max_price=max_price,
        province=province.strip() if province else None,
        city=city.strip() if city else None,
        publish_days=publish_days,
        personal_only=personal_only,
        free_shipping=free_shipping,
    )
    with _goofish_errors("搜索"):
        res = await get_runtime().gateway.search_items(query, account_id=account_id)
    # 入市场商品库：给商品分析提供同类价格样本与价格走势
    for item in res.items:
        await upsert_market_item(session, item)
    await session.commit()
    return res.model_dump()


@router.get("/items/{item_id}/detail")
async def get_item_detail(
    item_id: str,
    user: CurrentUser,
    session: SessionDep,
    account_id: int | None = None,
) -> dict[str, Any]:
    if account_id is not None:
        await get_account_for(session, user, account_id)
    with _goofish_errors("获取商品详情"):
        detail = await get_runtime().gateway.get_item_detail(item_id, account_id=account_id)
    await _save_detail(session, detail)
    return detail.model_dump()


# ---------------------------------------------------------------- 商品分析 / 商家分析
async def _peer_prices(session, user, item_id: str, task_id: int | None, keyword: str | None):  # noqa: ANN001, ANN202
    """同类价格样本：优先任务历史，其次关键词匹配市场商品库，最后回退到该商品所属的任务。"""
    since = datetime.now(UTC) - timedelta(days=30)
    if task_id is None and not (keyword or "").strip():
        task_id = (
            await session.execute(
                select(TaskResult.task_id)
                .join(MonitorTask, MonitorTask.id == TaskResult.task_id)
                .where(TaskResult.item_id == item_id, MonitorTask.owner_id == user.id)
                .limit(1)
            )
        ).scalar_one_or_none()
    if task_id is not None:
        await _own_task(session, user, task_id)
        stmt = (
            select(MarketItemRecord.price)
            .join(TaskResult, TaskResult.item_id == MarketItemRecord.item_id)
            .where(TaskResult.task_id == task_id, MarketItemRecord.last_seen_at >= since)
        )
        return [r[0] for r in await session.execute(stmt)], "task"
    words = [w for w in (keyword or "").split() if w][:5]
    if not words:
        return [], "none"
    stmt = select(MarketItemRecord.price).where(MarketItemRecord.last_seen_at >= since)
    for w in words:
        stmt = stmt.where(MarketItemRecord.title.ilike(f"%{w}%"))
    return [r[0] for r in await session.execute(stmt.limit(500))], "keyword"


async def _item_analysis(
    session,
    user,
    item_id: str,
    task_id: int | None,
    keyword: str | None,
    account_id: int | None,  # noqa: ANN001
) -> tuple[ItemAnalysis, MarketItemRecord]:
    rec = await session.get(MarketItemRecord, item_id)
    if rec is None or rec.detail_fetched_at is None:
        try:
            with _goofish_errors("获取商品详情"):
                detail = await get_runtime().gateway.get_item_detail(item_id, account_id=account_id)
            rec = await _save_detail(session, detail)
        except HTTPException:
            if rec is None:
                raise
    peers, source = await _peer_prices(session, user, item_id, task_id, keyword)
    snaps = await session.execute(
        select(PriceSnapshot).where(PriceSnapshot.item_id == item_id).order_by(PriceSnapshot.seen_at)
    )
    analysis = analyze_item(
        item_id=item_id,
        title=rec.title,
        price=rec.price,
        orig_price=rec.orig_price,
        want_cnt=rec.want_cnt,
        browse_cnt=rec.browse_cnt,
        publish_time=rec.publish_time,
        desc=rec.desc,
        images=list(rec.images or ([rec.image_url] if rec.image_url else [])),
        peers=[p for p in peers if p],
        sample_source=source,
        snapshots=[PricePoint(price=p.price, seen_at=p.seen_at) for p in snaps.scalars()],
        stats=market_stats(peers),
    )
    return analysis, rec


async def _seller_analysis(
    session,  # noqa: ANN001
    rec: MarketItemRecord,
    *,
    account_id: int | None,
    refresh: bool = False,
    ip_location: str = "",
    sold_cnt: int | None = None,
) -> SellerAnalysis:
    if not (rec.seller_id or "").isdigit():
        # 搜索结果只有加密卖家 ID，补一次详情拿到数字 ID
        with _goofish_errors("获取商品详情"):
            detail = await get_runtime().gateway.get_item_detail(rec.item_id, account_id=account_id)
        rec = await _save_detail(session, detail)
        sold_cnt = sold_cnt if sold_cnt is not None else detail.seller.sold_cnt
        ip_location = ip_location or detail.seller.ip_location
    seller_id = rec.seller_id
    if not seller_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "未获取到卖家信息")
    with _goofish_errors("获取卖家主页"):
        profile = await load_seller_profile(seller_id, account_id, refresh=refresh)
    cached = await session.get(SellerProfileCache, seller_id)
    analysis = analyze_seller(
        profile,
        item_area=rec.area,
        zhima=rec.seller_zhima,
        reg_days=rec.seller_reg_days,
        sold_cnt=sold_cnt,
        ip_hint=ip_location,
    )
    if cached is not None:  # SQLite 取回的是不带时区的 UTC 时间
        fetched = cached.fetched_at
        analysis.fetched_at = fetched if fetched.tzinfo else fetched.replace(tzinfo=UTC)
    return analysis


@router.get("/items/{item_id}/analysis", response_model=ItemAnalysis)
async def item_analysis(
    item_id: str,
    user: CurrentUser,
    session: SessionDep,
    task_id: int | None = None,
    keyword: str | None = Query(default=None, max_length=100),
    account_id: int | None = None,
) -> ItemAnalysis:
    if account_id is not None:
        await get_account_for(session, user, account_id)
    analysis, _ = await _item_analysis(session, user, item_id, task_id, keyword, account_id)
    return analysis


@router.get("/items/{item_id}/seller-analysis", response_model=SellerAnalysis)
async def seller_analysis(
    item_id: str,
    user: CurrentUser,
    session: SessionDep,
    account_id: int | None = None,
    refresh: bool = False,
    ip_location: str = Query(default="", max_length=32, description="详情接口已拿到的 IP 属地，主页未返回时兜底"),
    sold_cnt: int | None = Query(default=None, ge=0),
) -> SellerAnalysis:
    """商品所属卖家的分析：IP 属地 × 评价动态 × 在售商品（卖家主页 4 次接口调用，缓存 24 小时）。"""
    if account_id is not None:
        await get_account_for(session, user, account_id)
    rec = await session.get(MarketItemRecord, item_id)
    if rec is None:
        with _goofish_errors("获取商品详情"):
            detail = await get_runtime().gateway.get_item_detail(item_id, account_id=account_id)
        rec = await _save_detail(session, detail)
    return await _seller_analysis(
        session, rec, account_id=account_id, refresh=refresh, ip_location=ip_location, sold_cnt=sold_cnt
    )


class InsightIn(BaseModel):
    task_id: int | None = None
    keyword: str | None = Field(default=None, max_length=100)
    account_id: int | None = None
    ip_location: str = Field(default="", max_length=32)
    sold_cnt: int | None = None


class InsightResp(BaseModel):
    item: ItemAnalysis
    seller: SellerAnalysis | None
    ai: InsightOut


@router.post("/items/{item_id}/insight", response_model=InsightResp)
async def item_insight(item_id: str, body: InsightIn, user: CurrentUser, session: SessionDep) -> InsightResp:
    """商品 + 商家的大模型综合点评（会拉取卖家主页，受风控限速）。"""
    if body.account_id is not None:
        await get_account_for(session, user, body.account_id)
    item, rec = await _item_analysis(session, user, item_id, body.task_id, body.keyword, body.account_id)
    seller = None
    if rec.seller_id:
        seller = await _seller_analysis(
            session, rec, account_id=body.account_id, ip_location=body.ip_location, sold_cnt=body.sold_cnt
        )
    criteria = (await _own_task(session, user, body.task_id)).criteria if body.task_id else ""
    try:
        ai = await ai_insight(get_llm(), item, seller, criteria)
    except LLMUnavailable as e:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, f"大模型不可用：{e}") from e
    except LLMError as e:
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, str(e)) from e
    return InsightResp(item=item, seller=seller, ai=ai)
