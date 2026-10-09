from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin
from app.intelligence.bargain import BargainPolicy


class ItemStatus(StrEnum):
    ON_SALE = "on_sale"
    SOLD = "sold"
    OFFLINE = "offline"


class MyItem(IdMixin, TimestampMixin, Base):
    """卖家自己的商品 + 本地补充信息（底价、议价策略、知识库）。"""

    __tablename__ = "my_items"
    __table_args__ = (UniqueConstraint("account_id", "item_id"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("xy_accounts.id", ondelete="CASCADE"), index=True)
    item_id: Mapped[str] = mapped_column(String(32), index=True)
    title: Mapped[str] = mapped_column(String(256), default="")
    price: Mapped[float | None] = mapped_column(Float, nullable=True)
    image_url: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(16), default=ItemStatus.ON_SALE, index=True)
    desc: Mapped[str] = mapped_column(Text, default="")
    # 议价策略（底价不对买家暴露）
    floor_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    max_rounds: Mapped[int] = mapped_column(Integer, default=3)
    step_ratios: Mapped[list[float]] = mapped_column(JSON, default=lambda: [0.4, 0.3, 0.2, 0.1])
    gifts: Mapped[str] = mapped_column(String(128), default="")
    # 客服知识库：FAQ / 参数 / 瑕疵说明 / 使用教程
    knowledge: Mapped[str] = mapped_column(Text, default="")
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False)
    want_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # 商品数据（同步时从商品详情补全，帮助判断哪些商品该降价 / 重新编辑）
    browse_cnt: Mapped[int | None] = mapped_column(Integer, nullable=True)
    publish_time: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    stats_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    synced_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_polished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def bargain_policy(self) -> BargainPolicy | None:
        if not self.price or not self.floor_price or self.floor_price > self.price:
            return None
        return BargainPolicy(
            list_price=self.price,
            floor_price=self.floor_price,
            max_rounds=self.max_rounds,
            step_ratios=self.step_ratios or [0.4, 0.3, 0.2, 0.1],
            gifts=self.gifts,
        )


class DraftStatus(StrEnum):
    DRAFT = "draft"
    SCHEDULED = "scheduled"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class PublishDraftRecord(IdMixin, TimestampMixin, Base):
    __tablename__ = "publish_drafts"

    account_id: Mapped[int] = mapped_column(ForeignKey("xy_accounts.id", ondelete="CASCADE"), index=True)
    created_by: Mapped[int | None] = mapped_column(Integer, nullable=True)
    title: Mapped[str] = mapped_column(String(60), default="")
    desc: Mapped[str] = mapped_column(Text, default="")
    image_ids: Mapped[list[str]] = mapped_column(JSON, default=list)
    price: Mapped[float] = mapped_column(Float, default=0)
    orig_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    shipping: Mapped[str] = mapped_column(String(16), default="free")
    post_fee: Mapped[float] = mapped_column(Float, default=0)
    self_pickup: Mapped[bool] = mapped_column(Boolean, default=False)
    floor_price: Mapped[float | None] = mapped_column(Float, nullable=True)
    knowledge: Mapped[str] = mapped_column(Text, default="")
    is_virtual: Mapped[bool] = mapped_column(Boolean, default=False)
    status: Mapped[str] = mapped_column(String(16), default=DraftStatus.DRAFT, index=True)
    scheduled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # AI 生成草稿时的附加信息（候选标题、定价依据、待确认事项等），人工创建的草稿为空
    ai_meta: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
