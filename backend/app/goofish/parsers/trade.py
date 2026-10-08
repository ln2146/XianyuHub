"""卖家订单解析（已售列表 / 订单详情）。"""

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel

from app.goofish.parsers.common import dig, parse_int, parse_price


class OrderStatus(StrEnum):
    PENDING_PAY = "pending_pay"
    PAID = "paid"  # 待发货
    SHIPPED = "shipped"
    COMPLETED = "completed"
    CLOSED = "closed"
    REFUNDING = "refunding"
    REFUNDED = "refunded"
    UNKNOWN = "unknown"


STATUS_TEXT_MAP = {
    "待付款": OrderStatus.PENDING_PAY,
    "等待买家付款": OrderStatus.PENDING_PAY,
    "待发货": OrderStatus.PAID,
    "等待卖家发货": OrderStatus.PAID,
    "已发货": OrderStatus.SHIPPED,
    "等待买家收货": OrderStatus.SHIPPED,
    "交易成功": OrderStatus.COMPLETED,
    "交易关闭": OrderStatus.CLOSED,
    "退款关闭": OrderStatus.CLOSED,
    "退款中": OrderStatus.REFUNDING,
    "退款成功": OrderStatus.REFUNDED,
    "已退款": OrderStatus.REFUNDED,
}


def map_status(text: str | None) -> OrderStatus:
    if not text:
        return OrderStatus.UNKNOWN
    for key, status in STATUS_TEXT_MAP.items():
        if key in text:
            return status
    return OrderStatus.UNKNOWN


class RemoteOrder(BaseModel):
    order_id: str
    status: OrderStatus = OrderStatus.UNKNOWN
    status_text: str = ""
    item_id: str | None = None
    item_title: str = ""
    buyer_id: str | None = None
    buyer_nick: str = ""
    amount: float | None = None
    quantity: int = 1
    spec_name: str = ""
    spec_value: str = ""
    is_bargain: bool = False
    receiver_name: str = ""
    receiver_phone: str = ""
    receiver_address: str = ""
    created_at: datetime | None = None


def _parse_time(text: str | None) -> datetime | None:
    if not text:
        return None
    try:
        return datetime.strptime(text, "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
    except ValueError:
        return None


def parse_sold_list(data: dict[str, Any]) -> tuple[list[RemoteOrder], bool]:
    module = data.get("module") or {}
    out: list[RemoteOrder] = []
    for row in module.get("items") or []:
        common = row.get("commonData") or {}
        order_id = str(common.get("orderId") or "")
        if not order_id:
            continue
        buyer = row.get("buyerInfoVO") or {}
        price = row.get("priceVO") or {}
        status_text = str(common.get("orderStatus") or "")
        status = OrderStatus.REFUNDING if str(common.get("inRefund")) == "true" else map_status(status_text)
        btns = dig(row, "rightVO", "btnList", default=[]) or []
        out.append(
            RemoteOrder(
                order_id=order_id,
                status=status,
                status_text=status_text,
                item_id=str(common.get("itemId") or "") or None,
                item_title=dig(row, "itemVO", "title", default="") or "",
                buyer_id=str(buyer.get("buyerId") or "") or None,
                buyer_nick=buyer.get("userNick") or "",
                amount=parse_price(price.get("totalPrice")),
                quantity=parse_int(price.get("buyNum")) or 1,
                is_bargain=any(b.get("tradeAction") == "SKIP_PIN" for b in btns if isinstance(b, dict)),
                receiver_name=buyer.get("name") or "",
                receiver_phone=buyer.get("phone") or "",
                receiver_address=buyer.get("address") or "",
                created_at=_parse_time(common.get("createTime")),
            )
        )
    return out, str(module.get("nextPage")).lower() == "true"


def parse_order_detail(order_id: str, data: dict[str, Any]) -> RemoteOrder:
    order = RemoteOrder(order_id=order_id)
    for comp in data.get("components") or []:
        render = comp.get("render")
        cd = comp.get("data") or {}
        if render == "orderInfoVO":
            info = cd.get("itemInfo") or {}
            order.item_id = str(info.get("itemId") or "") or order.item_id
            order.item_title = info.get("title") or order.item_title
            order.amount = parse_price(info.get("price"))
            order.quantity = parse_int(info.get("buyAmount")) or 1
            sku = str(info.get("skuInfo") or "")
            if ":" in sku:
                name, _, value = sku.partition(":")
                order.spec_name, order.spec_value = name.strip(), value.strip()
            elif sku:
                order.spec_value = sku.strip()
        elif render == "addressInfoVO":
            order.receiver_name = cd.get("name") or ""
            order.receiver_phone = cd.get("phoneNumber") or ""
            order.receiver_address = cd.get("address") or ""
        elif render == "orderStatusVO":
            title = dig(cd, "orderStatusInfo", "title", default="") or ""
            nodes = cd.get("orderStatusNodeList") or []
            current = next((n.get("title") for n in nodes if isinstance(n, dict) and n.get("current")), None)
            order.status_text = current or title
            order.status = map_status(order.status_text)
    blob = str(data)
    if not order.buyer_id:
        m = re.search(r"'buyerId': '?(\d+)", blob)
        order.buyer_id = m.group(1) if m else None
    return order
