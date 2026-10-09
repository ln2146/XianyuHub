"""集中导入全部 ORM 模型，供 create_all / Alembic 使用。"""

from app.domains.account.models import AccountGrant, RiskEvent, XyAccount, XyAccountCredential  # noqa: F401
from app.domains.buyer.models import (  # noqa: F401
    MarketItemRecord,
    MonitorTask,
    PriceSnapshot,
    PriceWatch,
    SellerProfileCache,
    TaskResult,
)
from app.domains.goods.models import MyItem, PublishDraftRecord  # noqa: F401
from app.domains.message.models import ChatMessage, Conversation, ReplyRule, ReplySuggestion  # noqa: F401
from app.domains.order.models import (  # noqa: F401
    BuyerBlacklist,
    CardBinding,
    CardItem,
    CardPool,
    DeliveryRecord,
    Order,
)
from app.domains.system.models import AuditLog, LlmProvider, User  # noqa: F401
from app.notify.models import NotificationChannel  # noqa: F401
