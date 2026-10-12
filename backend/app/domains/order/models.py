from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class OrderState(StrEnum):
    PENDING_PAY = "pending_pay"
    PAID = "paid"
    RISK_HOLD = "risk_hold"  # 发货前风控命中，等待人工
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    DELIVER_FAILED = "deliver_failed"
    MANUAL = "manual"  # 超过重试次数 / 无法自动发货，需人工处理
    COMPLETED = "completed"
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    CLOSED = "closed"


# 面向用户的中文状态名（与前端 orderStatusMap 保持一致）
ORDER_STATE_LABELS: dict[str, str] = {
    OrderState.PENDING_PAY: "待付款",
    OrderState.PAID: "已付款",
    OrderState.RISK_HOLD: "风控暂停",
    OrderState.DELIVERING: "发货中",
    OrderState.DELIVERED: "已发货",
    OrderState.DELIVER_FAILED: "发货失败",
    OrderState.MANUAL: "待人工",
    OrderState.COMPLETED: "已完成",
    OrderState.REFUNDING: "退款中",
    OrderState.REFUNDED: "已退款",
    OrderState.CLOSED: "已关闭",
}


# 允许的状态迁移（其余迁移会被拒绝，保证状态机一致）
TRANSITIONS: dict[str, set[str]] = {
    OrderState.PENDING_PAY: {
        OrderState.PAID,
        OrderState.DELIVERING,
        OrderState.DELIVERED,
        OrderState.COMPLETED,
        OrderState.CLOSED,
        OrderState.REFUNDED,
    },
    OrderState.PAID: {
        OrderState.DELIVERING,
        OrderState.RISK_HOLD,
        OrderState.DELIVERED,
        OrderState.REFUNDING,
        OrderState.CLOSED,
        OrderState.MANUAL,
        OrderState.COMPLETED,
    },
    OrderState.RISK_HOLD: {
        OrderState.PAID,
        OrderState.CLOSED,
        OrderState.REFUNDING,
        OrderState.DELIVERED,
        OrderState.COMPLETED,
        OrderState.MANUAL,
    },
    OrderState.DELIVERING: {
        OrderState.DELIVERED,
        OrderState.DELIVER_FAILED,
        OrderState.MANUAL,
        OrderState.REFUNDING,
        OrderState.CLOSED,
        OrderState.COMPLETED,
    },
    OrderState.DELIVER_FAILED: {
        OrderState.DELIVERING,
        OrderState.MANUAL,
        OrderState.REFUNDING,
        OrderState.DELIVERED,
        OrderState.CLOSED,
        OrderState.COMPLETED,
        OrderState.REFUNDED,
    },
    OrderState.MANUAL: {
        OrderState.DELIVERING,
        OrderState.DELIVERED,
        OrderState.REFUNDING,
        OrderState.CLOSED,
        OrderState.COMPLETED,
        OrderState.REFUNDED,
    },
    OrderState.DELIVERED: {OrderState.COMPLETED, OrderState.REFUNDING, OrderState.CLOSED, OrderState.REFUNDED},
    OrderState.COMPLETED: {OrderState.REFUNDING, OrderState.REFUNDED},
    OrderState.REFUNDING: {OrderState.REFUNDED, OrderState.DELIVERED, OrderState.COMPLETED, OrderState.CLOSED},
    OrderState.REFUNDED: set(),
    OrderState.CLOSED: set(),
}


class Order(IdMixin, TimestampMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (UniqueConstraint("account_id", "order_id"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("xy_accounts.id", ondelete="CASCADE"), index=True)
    order_id: Mapped[str] = mapped_column(String(32), index=True)
    item_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    item_title: Mapped[str] = mapped_column(String(256), default="")
    buyer_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    buyer_nick: Mapped[str] = mapped_column(String(64), default="")
    cid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    amount: Mapped[float | None] = mapped_column(Float, nullable=True)
    quantity: Mapped[int] = mapped_column(Integer, default=1)
    spec_name: Mapped[str] = mapped_column(String(64), default="")
    spec_value: Mapped[str] = mapped_column(String(128), default="")
    status: Mapped[str] = mapped_column(String(16), default=OrderState.PENDING_PAY, index=True)
    remote_status: Mapped[str] = mapped_column(String(32), default="")
    is_bargain: Mapped[bool] = mapped_column(Boolean, default=False)
    paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 平台付款事件时间；paid_at 的历史值可能是创建/观察时间，不能用于日成交统计。
    actual_paid_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    fail_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    next_retry_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 实物订单付款后长时间未发货的提醒（每单只提醒一次）
    ship_reminded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    rated: Mapped[bool] = mapped_column(Boolean, default=False)


class CardPool(IdMixin, TimestampMixin, Base):
    """卡券：text 固定文本；pool 卡密库存（一卡一用）；api 外部接口取货。都可以附带图片。"""

    __tablename__ = "card_pools"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(8))  # text / pool / api
    text_enc: Mapped[str | None] = mapped_column(Text, nullable=True)  # kind=text 的内容（加密）
    api_config: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    images: Mapped[list[str]] = mapped_column(JSON, default=list)  # 发货时随文字一起发给买家的图片（本地上传 ID）
    low_stock_threshold: Mapped[int] = mapped_column(Integer, default=5)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)


class CardItem(IdMixin, Base):
    __tablename__ = "card_items"
    # 同一库里同一张卡只能有一条：并发导入时由数据库兜底去重
    __table_args__ = (UniqueConstraint("pool_id", "fingerprint", name="uq_card_items_pool_fingerprint"),)

    pool_id: Mapped[int] = mapped_column(ForeignKey("card_pools.id", ondelete="CASCADE"), index=True)
    content_enc: Mapped[str] = mapped_column(Text)
    fingerprint: Mapped[str] = mapped_column(String(64), index=True)  # 去重用（sha256）
    status: Mapped[str] = mapped_column(String(10), default="available", index=True)  # available/locked/used
    order_pk: Mapped[int | None] = mapped_column(Integer, nullable=True)
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class CardBinding(IdMixin, TimestampMixin, Base):
    """商品（+规格）→ 卡券。account_id 为空表示对所有账号的同 item_id 生效。"""

    __tablename__ = "card_bindings"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    pool_id: Mapped[int] = mapped_column(ForeignKey("card_pools.id", ondelete="CASCADE"))
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    item_id: Mapped[str] = mapped_column(String(32), index=True)
    spec_value: Mapped[str | None] = mapped_column(String(128), nullable=True)
    template: Mapped[str] = mapped_column(Text, default="")
    delay_seconds: Mapped[int] = mapped_column(Integer, default=0)
    max_per_buyer: Mapped[int] = mapped_column(Integer, default=0)  # 同一买家 24 小时内最多自动发货次数，0 不限
    # 商品卖完下架后，自动发布一件同样的新商品（库存只能为 1 的账号用来持续售卖电子资料等）
    auto_relist: Mapped[bool] = mapped_column(Boolean, default=False)


class DeliveryRecord(IdMixin, Base):
    __tablename__ = "delivery_records"

    order_pk: Mapped[int] = mapped_column(ForeignKey("orders.id", ondelete="CASCADE"), index=True)
    pool_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    card_item_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    preview: Mapped[str] = mapped_column(String(64), default="")
    mode: Mapped[str] = mapped_column(String(24), default="")
    message_sent: Mapped[bool] = mapped_column(Boolean, default=False)
    consigned: Mapped[bool] = mapped_column(Boolean, default=False)
    success: Mapped[bool] = mapped_column(Boolean, default=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class BuyerBlacklist(IdMixin, Base):
    __tablename__ = "buyer_blacklist"
    __table_args__ = (UniqueConstraint("owner_id", "buyer_id"),)

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    buyer_id: Mapped[str] = mapped_column(String(32))
    reason: Mapped[str] = mapped_column(String(256), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
