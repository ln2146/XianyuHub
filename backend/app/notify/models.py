from sqlalchemy import JSON, Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin


class NotificationChannel(IdMixin, TimestampMixin, Base):
    __tablename__ = "notification_channels"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    name: Mapped[str] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(String(16))  # wecom/feishu/dingtalk/telegram/bark/ntfy/webhook/email
    # 渠道配置中含 webhook token 等敏感信息，整体加密存储
    config_enc: Mapped[str] = mapped_column(Text)
    events: Mapped[list[str]] = mapped_column(JSON, default=list)  # 为空表示订阅全部
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)

    def wants(self, event: str) -> bool:
        return self.enabled and (not self.events or event in self.events)
