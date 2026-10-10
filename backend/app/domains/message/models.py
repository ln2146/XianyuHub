from datetime import datetime
from enum import StrEnum

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base, IdMixin, TimestampMixin, utcnow


class MessageSource(StrEnum):
    BUYER = "buyer"
    SELLER_APP = "seller_app"  # 卖家在闲鱼 App / 网页亲自发送
    WEB_MANUAL = "web_manual"  # 在本系统收件箱人工发送
    AUTO_KEYWORD = "auto_keyword"
    AUTO_AI = "auto_ai"
    AUTO_DEFAULT = "auto_default"
    DELIVERY = "delivery"  # 自动发货
    SYSTEM = "system"  # 平台系统消息


class Conversation(IdMixin, TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("account_id", "cid"),)

    account_id: Mapped[int] = mapped_column(ForeignKey("xy_accounts.id", ondelete="CASCADE"), index=True)
    cid: Mapped[str] = mapped_column(String(64))
    peer_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    peer_name: Mapped[str] = mapped_column(String(64), default="")
    item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    last_message: Mapped[str] = mapped_column(Text, default="")
    last_message_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    unread: Mapped[int] = mapped_column(Integer, default=0)
    takeover_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    bargain_rounds: Mapped[int] = mapped_column(Integer, default=0)
    bargain_last_offer: Mapped[float | None] = mapped_column(Float, nullable=True)
    default_replied: Mapped[bool] = mapped_column(Boolean, default=False)
    handled_upto_id: Mapped[int] = mapped_column(Integer, default=0)  # 自动回复已处理到的消息 ID
    tags: Mapped[list[str]] = mapped_column(JSON, default=list)


class ChatMessage(IdMixin, Base):
    __tablename__ = "chat_messages"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int] = mapped_column(Integer, index=True)
    direction: Mapped[str] = mapped_column(String(4))  # in / out
    source: Mapped[str] = mapped_column(String(16))
    sender_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    text: Mapped[str] = mapped_column(Text, default="")
    is_system: Mapped[bool] = mapped_column(Boolean, default=False)
    notice: Mapped[str | None] = mapped_column(String(24), nullable=True)
    meta: Mapped[dict] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)


class ReplyRule(IdMixin, TimestampMixin, Base):
    """关键词回复规则。account_id 为空表示对 owner 的所有账号生效；item_id 为空表示对所有商品生效。"""

    __tablename__ = "reply_rules"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    item_id: Mapped[str | None] = mapped_column(String(32), nullable=True)
    name: Mapped[str] = mapped_column(String(64), default="")
    keywords: Mapped[list[str]] = mapped_column(JSON, default=list)
    match: Mapped[str] = mapped_column(String(8), default="contains")  # contains / exact / regex
    reply: Mapped[str] = mapped_column(Text)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    reply_once: Mapped[bool] = mapped_column(Boolean, default=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    hits: Mapped[int] = mapped_column(Integer, default=0)


class ReplySuggestion(IdMixin, Base):
    """建议模式下 AI 生成的候选回复，等待人工一键发送。"""

    __tablename__ = "reply_suggestions"

    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    text: Mapped[str] = mapped_column(Text)
    intent: Mapped[str] = mapped_column(String(16), default="")
    status: Mapped[str] = mapped_column(String(12), default="pending")  # pending / sent / discarded
    note: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class KnowledgeDoc(IdMixin, TimestampMixin, Base):
    """卖家上传给 AI 客服参考的资料（说明书、FAQ、价目表等），保存提取出的纯文本。
    回复时按与买家问题的相关度挑选段落放进提示词，不整篇发送。"""

    __tablename__ = "knowledge_docs"

    owner_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    account_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)  # 为空表示所有账号通用
    name: Mapped[str] = mapped_column(String(200))
    content: Mapped[str] = mapped_column(Text, default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
