from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Verdict(StrEnum):
    RECOMMEND = "recommend"
    CONDITIONAL = "conditional"
    REJECT = "reject"


class ResultStage(StrEnum):
    FILTERED = "filtered"  # 规则初筛未通过
    PRESCREEN_REJECTED = "prescreen_rejected"  # 文本粗筛淘汰
    EVALUATED = "evaluated"  # 已完成判定
    ERROR = "error"


class UserMark(StrEnum):
    NONE = "none"
    FAVORITE = "favorite"
    IGNORED = "ignored"
    BOUGHT = "bought"
    SEEN = "seen"


class MonitorTask(IdMixin, TimestampMixin, Base):
    __tablename__ = "buyer_tasks"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    # 搜索参数（走接口参数筛选）
    min_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    province: Mapped[str | None] = mapped_column(String(32), nullable=True)
    city: Mapped[str | None] = mapped_column(String(32), nullable=True)
    publish_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    personal_only: Mapped[bool] = mapped_column(Boolean, default=False)
    free_shipping: Mapped[bool] = mapped_column(Boolean, default=False)
    sort: Mapped[str] = mapped_column(String(16), default="newest")
    max_pages: Mapped[int] = mapped_column(Integer, default=1)
    # 规则初筛（ItemRules）与 AI 判定标准
    rules: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    criteria: Mapped[str] = mapped_column(Text, default="")
    decision_mode: Mapped[str] = mapped_column(String(8), default="ai")  # ai / rule
    analyze_images: Mapped[bool] = mapped_column(Boolean, default=True)
    ai_prescreen: Mapped[bool] = mapped_column(Boolean, default=True)
    fetch_seller_profile: Mapped[bool] = mapped_column(Boolean, default=False)
    notify_conditional: Mapped[bool] = mapped_column(Boolean, default=False)
    price_drop_percent: Mapped[float] = mapped_column(Float, default=5.0)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 为空则匿名搜索
    cron: Mapped[str] = mapped_column(String(64), default="*/30 8-23 * * *")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    # 运行状态
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_status: Mapped[str | None] = mapped_column(String(16), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    last_stats: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    consecutive_failures: Mapped[int] = mapped_column(Integer, default=0)
    paused_reason: Mapped[str | None] = mapped_column(Text, nullable=True)


class MarketItemRecord(Base):
    """市场商品库：所有任务共享，用于价格情报与降价追踪。"""

    __tablename__ = "market_items"

    item_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    orig_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    want_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    browse_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    area: Mapped[str] = mapped_column(String(64), default="")
    seller_nick: Mapped[str] = mapped_column(String(64), default="")
    seller_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    seller_zhima: Mapped[str] = mapped_column(String(16), default="")
    seller_reg_days: Mapped[int | None] = mapped_column(Integer, nullable=True)
    image_url: Mapped[str] = mapped_column(String(512), default="")
    images: Mapped[list[str]] = mapped_column(JSON, default=list)
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    desc: Mapped[str] = mapped_column(Text, default="")
    link: Mapped[str] = mapped_column(String(512), default="")
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail_fetched_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class PriceSnapshot(IdMixin, Base):
    __tablename__ = "price_snapshots"

    item_id: Mapped[str] = mapped_column(String(32), index=True)
    price: Mapped[float] = mapped_column(Float)
    seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class TaskResult(IdMixin, Base):
    __tablename__ = "buyer_results"
    __table_args__ = (UniqueConstraint("task_id", "item_id"),)

    task_id: Mapped[int] = mapped_column(ForeignKey("buyer_tasks.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(32), index=True)
    stage: Mapped[str] = mapped_column(String(24), default=ResultStage.FILTERED)
    filter_reasons: Mapped[list[str]] = mapped_column(JSON, default=list)
    verdict: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)
    confidence: Mapped[float | None] = mapped_column(Float, nullable=True)
    reason: Mapped[str] = mapped_column(Text, default="")
    risk_tags: Mapped[list[str]] = mapped_column(JSON, default=list)
    need_confirm: Mapped[list[str]] = mapped_column(JSON, default=list)
    questions: Mapped[list[str]] = mapped_column(JSON, default=list)
    seller_type: Mapped[str | None] = mapped_column(String(16), nullable=True)
    deal_score: Mapped[int | None] = mapped_column(Integer, nullable=True)
    price_at_eval: Mapped[float | None] = mapped_column(Float, nullable=True)
    ai_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    mark: Mapped[str] = mapped_column(String(16), default=UserMark.NONE)
    notified: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class SellerProfileCache(Base):
    __tablename__ = "seller_profiles"

    seller_id: Mapped[str] = mapped_column(String(32), primary_key=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
