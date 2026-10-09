from datetime import datetime
from enum import StrEnum
from typing import Any

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class Role(StrEnum):
    ADMIN = "admin"
    OPERATOR = "operator"
    MEMBER = "member"


class User(IdMixin, TimestampMixin, Base):
    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[str] = mapped_column(String(16), default=Role.MEMBER)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    failed_attempts: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ActorType(StrEnum):
    HUMAN = "human"
    RULE = "rule"
    AI = "ai"
    SYSTEM = "system"


class AuditLog(IdMixin, Base):
    """所有写操作的审计记录：谁（人 / 规则 / AI）对哪个账号做了什么。"""

    __tablename__ = "audit_logs"

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    actor_type: Mapped[str] = mapped_column(String(16), default=ActorType.HUMAN)
    action: Mapped[str] = mapped_column(String(64), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    target_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    success: Mapped[bool] = mapped_column(Boolean, default=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)


class LlmProvider(IdMixin, TimestampMixin, Base):
    """大模型接入配置（全局唯一一份，由管理员在管理台维护）。

    同时最多只有一个 enabled + is_active 的配置生效；没有任何生效配置时回退到环境变量。
    api_key 与其他凭证一样用 Vault 加密后落库。
    """

    __tablename__ = "llm_providers"

    name: Mapped[str] = mapped_column(String(64), unique=True)
    kind: Mapped[str] = mapped_column(String(32))  # anthropic / openai_compatible
    base_url: Mapped[str] = mapped_column(String(256), default="")
    api_key_enc: Mapped[str] = mapped_column(Text, default="")
    # 三个档位分别对应：多模态判定与文案 / 客服回复 / 意图分类与粗筛
    model_vision: Mapped[str] = mapped_column(String(128), default="")
    model_chat: Mapped[str] = mapped_column(String(128), default="")
    model_fast: Mapped[str] = mapped_column(String(128), default="")
    timeout_seconds: Mapped[float] = mapped_column(Float, default=90.0)
    anthropic_fallbacks: Mapped[bool] = mapped_column(Boolean, default=True)
    daily_token_budget: Mapped[int | None] = mapped_column(Integer, nullable=True)  # 为空表示沿用全局设置
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False, index=True)
    last_test_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_test_ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
