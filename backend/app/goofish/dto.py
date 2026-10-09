"""闲鱼适配层输出的统一数据结构（与通道无关）。"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class MarketItem(BaseModel):
    item_id: str
    title: str = ""
    price: float | None = None
    price_text: str = ""
    orig_price: float | None = None
    want_cnt: int | None = None
    browse_cnt: int | None = None
    area: str = ""
    seller_nick: str = ""
    seller_id: str | None = None
    image_url: str = ""
    images: list[str] = Field(default_factory=list)
    publish_time: datetime | None = None
    link: str = ""
    tags: list[str] = Field(default_factory=list)
    desc: str = ""


class SellerInfo(BaseModel):
    seller_id: str | None = None
    nick: str = ""
    zhima_level: str = ""
    reg_days: int | None = None
    sold_cnt: int | None = None
    ip_location: str = ""  # IP 属地（省级），接口未返回时为空


class ItemDetail(BaseModel):
    item: MarketItem
    seller: SellerInfo
    status: str = ""
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)


class SearchQuery(BaseModel):
    keyword: str
    page: int = 1
    sort: str = "newest"  # newest / price_asc / price_desc / default
    min_price: int | None = None
    max_price: int | None = None
    province: str | None = None
    city: str | None = None
    publish_days: int | None = None
    personal_only: bool = False
    free_shipping: bool = False


class SearchPage(BaseModel):
    items: list[MarketItem]
    page: int
    has_more: bool


class SellerRating(BaseModel):
    rate_id: str | None = None
    content: str = ""
    rate: int | None = None  # 1 好评 0 中评 -1 差评
    role: str = ""  # 来自买家 / 来自卖家
    rater_nick: str = ""
    created_at: str = ""


class SellerProfile(BaseModel):
    seller_id: str
    nick: str = ""
    avatar: str = ""
    introduction: str = ""
    item_cnt: int | None = None
    rate_cnt: int | None = None
    seller_credit: str = ""
    buyer_credit: str = ""
    ip_location: str = ""
    items: list[dict[str, Any]] = Field(default_factory=list)
    ratings: list[SellerRating] = Field(default_factory=list)

    @property
    def seller_positive_rate(self) -> float | None:
        rs = [r for r in self.ratings if "买家" in r.role]  # 来自买家的评价 = 作为卖家收到的评价
        if not rs:
            return None
        return sum(1 for r in rs if r.rate == 1) / len(rs)


class ImEventType(StrEnum):
    CHAT = "chat"
    ORDER = "order"
    TYPING = "typing"
    UNKNOWN = "unknown"


class SystemNotice(StrEnum):
    """从系统消息文案识别出的交易事件。"""

    NONE = "none"
    ORDER_CREATED = "order_created"
    PAID = "paid"
    SHIPPED = "shipped"
    RECEIVED = "received"
    CLOSED = "closed"
    REFUND = "refund"
    RATE_REQUEST = "rate_request"
    BARGAIN_CARD = "bargain_card"


class ImEvent(BaseModel):
    type: ImEventType
    cid: str | None = None  # 会话 ID（不含 @goofish）
    sender_id: str | None = None
    sender_name: str = ""
    text: str = ""
    item_id: str | None = None
    order_id: str | None = None
    created_at: datetime | None = None
    is_system: bool = False
    notice: SystemNotice = SystemNotice.NONE
    status_text: str = ""
    raw: dict[str, Any] = Field(default_factory=dict, exclude=True)
