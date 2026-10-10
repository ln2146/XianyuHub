from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field
from sqlalchemy import JSON, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class AccountSettings(BaseModel):
    """账号级自动化开关。所有自动写操作默认关闭。"""

    # 消息
    auto_reply: bool = False
    keyword_reply: bool = True
    # AI 回复需要卖家自己选择开启：默认关闭（建议模式即使总开关关闭也会调用模型、消耗额度）
    ai_mode: Literal["off", "suggest", "auto"] = "off"
    # 给 AI 的说明：店铺介绍、语气、发货 / 售后规则等；不能覆盖底价、站外联系等护栏
    ai_instructions: str = Field(default="", max_length=2000)
    takeover_minutes: int = Field(default=60, ge=1, le=24 * 60)
    reply_delay_min: float = Field(default=2, ge=0)
    reply_delay_max: float = Field(default=6, ge=0)
    merge_window_seconds: float = Field(default=5, ge=0, le=30)
    work_hours: str | None = None  # 例如 "09:00-23:00"，为空表示全天
    default_reply: str | None = None
    # 发货
    auto_delivery: bool = False
    delivery_mode: Literal["confirm_then_send", "send_then_confirm", "send_only"] = "send_then_confirm"
    auto_rate: bool = False
    rate_text: str = "感谢支持，欢迎再来～"
    # 运营
    auto_polish: bool = False
    # 发布：上次使用的宝贝所在地，新草稿默认沿用
    publish_location: dict[str, Any] | None = None


class XyAccount(IdMixin, TimestampMixin, Base):
    __tablename__ = "xy_accounts"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    unb: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    nickname: Mapped[str] = mapped_column(String(64), default="")
    remark: Mapped[str] = mapped_column(String(128), default="")
    avatar: Mapped[str] = mapped_column(String(512), default="")
    device_id: Mapped[str] = mapped_column(String(80))
    status: Mapped[str] = mapped_column(String(16), default="need_login", index=True)
    health_score: Mapped[int] = mapped_column(Integer, default=100)
    strikes: Mapped[int] = mapped_column(Integer, default=0)
    cooldown_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    punish_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    proxy_enc: Mapped[str | None] = mapped_column(Text, nullable=True)
    settings: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    last_probe_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    def get_settings(self) -> AccountSettings:
        return AccountSettings.model_validate(self.settings or {})


class XyAccountCredential(IdMixin, Base):
    """账号凭证单独成表，避免列表查询时把密文带出来。"""

    __tablename__ = "xy_account_credentials"

    account_id: Mapped[int] = mapped_column(ForeignKey("xy_accounts.id", ondelete="CASCADE"), unique=True)
    cookie_enc: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class AccountGrant(IdMixin, Base):
    """把账号授权给其他用户（客服 / 运营）。"""

    __tablename__ = "xy_account_grants"
    __table_args__ = (UniqueConstraint("user_id", "account_id"),)

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(ForeignKey("xy_accounts.id", ondelete="CASCADE"), index=True)


class RiskEvent(IdMixin, Base):
    __tablename__ = "xy_risk_events"

    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    guard_key: Mapped[str] = mapped_column(String(32))
    state: Mapped[str] = mapped_column(String(16))
    reason: Mapped[str] = mapped_column(Text, default="")
    punish_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
