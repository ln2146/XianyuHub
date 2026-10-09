"""闲鱼适配层输出的统一数据结构（与通道无关）。"""

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field


class TagIcon(BaseModel):
    """搜索卡片上的图片标签（包邮、描述不符包邮退、7 天无理由等），直接用闲鱼的图标渲染。"""

    name: str
    url: str
    row: str = ""  # r1 = 标题前，r5 = 服务标签行
    width: int | None = None
    height: int | None = None


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
    # 以下仅搜索结果卡片有（fishTags 各行）
    avatar: str = ""
    attrs: list[str] = Field(default_factory=list)  # r2：成色 / 品牌 / 规格
    price_note: str = ""  # r3：累计降价等
    seller_tags: list[str] = Field(default_factory=list)  # r4：卖家信用极好 / 回复超快
    icons: list[TagIcon] = Field(default_factory=list)  # r1 / r5 图片标签


# 网页版搜索的快捷筛选（勾选框），取值来自对 goofish.com 搜索请求的抓包
QUICK_FILTERS = {
    "filterPersonal": "个人闲置",
    "filterAppraise": "验货宝",
    "gameAccountInsurance": "验号担保",
    "filterFreePostage": "包邮",
    "filterHighLevelYxpSeller": "超赞鱼小铺",
    "filterNew": "全新",
    "inspectedPhone": "严选",
    "filterOneKeyResell": "转卖",
}


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
    sort: str = "newest"  # newest / price_asc / price_desc / reduce（新降价） / default
    min_price: int | None = None
    max_price: int | None = None
    province: str | None = None
    city: str | None = None
    publish_days: int | None = None
    personal_only: bool = False
    free_shipping: bool = False
    quick_filters: list[str] = Field(default_factory=list)  # QUICK_FILTERS 的键


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
