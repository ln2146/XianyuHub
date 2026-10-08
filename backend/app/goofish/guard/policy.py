"""各能力的风控策略：限流速率、是否写操作、是否需要账号互斥。"""

from dataclasses import dataclass
from enum import StrEnum

from app.core.config import get_settings


class Action(StrEnum):
    SEARCH = "search"
    DETAIL = "detail"
    SELLER_PROFILE = "seller_profile"
    MY_ITEMS = "my_items"
    USER_PROBE = "user_probe"
    IM_TOKEN = "im_token"
    SEND_MESSAGE = "send_message"
    ORDER_QUERY = "order_query"
    CONSIGN = "consign"
    UPLOAD = "upload"
    CATEGORY = "category"
    PUBLISH = "publish"
    EDIT_ITEM = "edit_item"
    POLISH = "polish"
    RATE = "rate"
    LOGIN = "login"


@dataclass(frozen=True)
class ActionPolicy:
    rate: float  # 每 per 秒允许的次数
    per: float = 60.0
    burst: float = 1.0
    write: bool = False
    exclusive: bool = False  # 同一账号同一时刻只允许一个（登录 / 发布类）
    max_wait: float = 120.0  # 排队等待令牌的上限，超过则拒绝
    requires_login: bool = True


def policies() -> dict[Action, ActionPolicy]:
    s = get_settings()
    return {
        Action.SEARCH: ActionPolicy(rate=s.guard_search_per_min, burst=2, requires_login=False),
        Action.DETAIL: ActionPolicy(rate=s.guard_detail_per_min, burst=2, requires_login=False),
        Action.SELLER_PROFILE: ActionPolicy(rate=3, requires_login=False),
        Action.MY_ITEMS: ActionPolicy(rate=2),
        Action.USER_PROBE: ActionPolicy(rate=6),
        Action.IM_TOKEN: ActionPolicy(rate=4),
        Action.SEND_MESSAGE: ActionPolicy(rate=s.guard_message_per_min, burst=3, write=True, max_wait=30),
        Action.ORDER_QUERY: ActionPolicy(rate=6, burst=2),
        Action.CONSIGN: ActionPolicy(rate=10, burst=2, write=True),
        Action.UPLOAD: ActionPolicy(rate=10, burst=3, write=True),
        Action.CATEGORY: ActionPolicy(rate=6),
        Action.PUBLISH: ActionPolicy(rate=s.guard_publish_per_5min, per=300, write=True, exclusive=True, max_wait=600),
        Action.EDIT_ITEM: ActionPolicy(rate=1, write=True, exclusive=True),
        Action.POLISH: ActionPolicy(rate=1, write=True),
        Action.RATE: ActionPolicy(rate=2, write=True),
        Action.LOGIN: ActionPolicy(rate=2, per=300, exclusive=True, requires_login=False),
    }
