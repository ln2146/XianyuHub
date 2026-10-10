"""IM 消息解析：把解码后的推送结构转换为 ImEvent。

系统消息文案（付款、发货等）集中在 NOTICE_RULES 中，平台改文案时只需更新这里。
"""

import json
import re
from typing import Any
from urllib.parse import parse_qs, urlparse

from app.goofish.dto import ImEvent, ImEventType, SystemNotice
from app.goofish.parsers.common import dig, parse_ms

# 顺序即优先级
NOTICE_RULES: list[tuple[SystemNotice, tuple[str, ...]]] = [
    (SystemNotice.PAID, ("我已付款，等待你发货", "已付款，待发货", "记得及时发货", "我已付款，请添加自提信息")),
    (SystemNotice.ORDER_CREATED, ("我已拍下，待付款", "等待买家付款")),
    (SystemNotice.SHIPPED, ("你已发货", "已发货")),
    (SystemNotice.RECEIVED, ("确认收货", "交易成功")),
    (SystemNotice.CLOSED, ("交易关闭", "订单已关闭")),
    (SystemNotice.REFUND, ("申请退款", "退款")),
    (SystemNotice.RATE_REQUEST, ("快给ta一个评价吧", "去评价")),
    (SystemNotice.BARGAIN_CARD, ("小刀",)),
]

# 平台插进会话里的提示：发送者显示为买家，但不是买家打的字（买家也打不出 <font> 这类排版标记）
PLATFORM_TIP_MARKERS = ("<font", "蚂蚁森林能量", "商品信息近期有过变更")
# 买家自己发的内容类型：1 文字、2 图片；其他（卡片、提示条等）都是平台消息
USER_CONTENT_TYPES = {1, 2}

_ORDER_ID_PATTERNS = [
    re.compile(r"orderId=(\d{6,})"),
    re.compile(r"order_detail\?id=(\d{6,})"),
    re.compile(r"[\"']orderId[\"']\s*:\s*[\"']?(\d{6,})"),
    re.compile(r"bizOrderId=(\d{6,})"),
]


def classify_notice(text: str) -> SystemNotice:
    if not text:
        return SystemNotice.NONE
    for notice, words in NOTICE_RULES:
        if any(w in text for w in words):
            return notice
    return SystemNotice.NONE


def extract_order_id(message: Any) -> str | None:
    blob = message if isinstance(message, str) else json.dumps(message, ensure_ascii=False)
    for p in _ORDER_ID_PATTERNS:
        m = p.search(blob)
        if m:
            return m.group(1)
    return None


def _item_id_from_url(url: str | None) -> str | None:
    if not url:
        return None
    qs = parse_qs(urlparse(url).query)
    for key in ("itemId", "item_id", "id"):
        if qs.get(key):
            return qs[key][0]
    m = re.search(r"itemId=(\d+)", url)
    return m.group(1) if m else None


def _content_type(blob: Any) -> int | None:
    if not isinstance(blob, str) or not blob.startswith("{"):
        return None
    try:
        value = json.loads(blob).get("contentType")
    except (ValueError, AttributeError):
        return None
    return value if isinstance(value, int) else None


def _strip_cid(cid: str | None) -> str | None:
    return cid.split("@", 1)[0] if cid else None


def parse_message(message: Any) -> ImEvent:
    if not isinstance(message, dict):
        return ImEvent(type=ImEventType.UNKNOWN, raw={"value": message})

    # 订单状态卡片：{"1": "uid@goofish", "3": {"redReminder": "等待卖家发货"}}
    red = dig(message, "3", "redReminder")
    if red and isinstance(message.get("1"), str):
        return ImEvent(
            type=ImEventType.ORDER,
            sender_id=_strip_cid(message["1"]),
            status_text=red,
            notice=classify_notice(red),
            order_id=extract_order_id(message),
            raw=message,
        )

    # 输入中状态：{"1": [{"1": "uid@goofish", ...}]}
    first = message.get("1")
    if isinstance(first, list) and first and isinstance(first[0], dict) and "@goofish" in str(first[0].get("1", "")):
        return ImEvent(type=ImEventType.TYPING, sender_id=_strip_cid(first[0]["1"]), raw=message)

    body = first if isinstance(first, dict) else {}
    reminder = body.get("10") if isinstance(body.get("10"), dict) else None
    if reminder and "reminderContent" in reminder:
        text = str(reminder.get("reminderContent") or "")
        is_system = text.startswith("[") and text.endswith("]")
        notice = classify_notice(text) if is_system else SystemNotice.NONE
        content_blob = dig(body, "6", "3", "5")
        content_type = _content_type(content_blob)
        if is_system and notice == SystemNotice.NONE and content_type in USER_CONTENT_TYPES:
            is_system = False  # 买家发的图片等，提醒文案也是「[图片]」这样的方括号形式
        if not is_system and isinstance(content_blob, str) and "dxCard" in content_blob:
            is_system = True
            notice = classify_notice(content_blob)
        elif not is_system and (
            (content_type is not None and content_type not in USER_CONTENT_TYPES)
            or any(m in text for m in PLATFORM_TIP_MARKERS)
        ):
            is_system = True
        return ImEvent(
            type=ImEventType.CHAT,
            cid=_strip_cid(body.get("2")),
            sender_id=str(reminder.get("senderUserId") or "") or None,
            sender_name=str(reminder.get("reminderTitle") or ""),
            text=text,
            item_id=_item_id_from_url(reminder.get("reminderUrl")),
            order_id=extract_order_id(message) if notice != SystemNotice.NONE else None,
            created_at=parse_ms(body.get("5")),
            is_system=is_system,
            notice=notice,
            content_type=content_type,
            raw=message,
        )
    return ImEvent(type=ImEventType.UNKNOWN, raw=message)
