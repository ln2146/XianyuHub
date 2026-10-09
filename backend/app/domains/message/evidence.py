"""售后 / 纠纷举证材料：把一个会话相关的订单、发货记录和完整聊天记录整理成一份 Markdown，
方便卖家提交闲鱼客服或小法庭。只整理系统里已有的事实，不做任何判断。"""

from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domains.account.models import XyAccount
from app.domains.goods.models import MyItem
from app.domains.message.models import ChatMessage, Conversation, MessageSource
from app.domains.order.models import ORDER_STATE_LABELS, DeliveryRecord, Order

TZ = ZoneInfo("Asia/Shanghai")

_SOURCE = {
    MessageSource.SELLER_APP: "我（闲鱼 App）",
    MessageSource.WEB_MANUAL: "我（管理台）",
    MessageSource.AUTO_KEYWORD: "我（关键词自动回复）",
    MessageSource.AUTO_AI: "我（AI 自动回复）",
    MessageSource.AUTO_DEFAULT: "我（默认回复）",
    MessageSource.DELIVERY: "我（自动发货）",
}

CHECKLIST = (
    "商品发货前的实拍照片 / 视频（含序列号、IMEI、已知瑕疵）",
    "打包、封箱到交给快递的完整视频",
    "快递单号与物流轨迹截图（签收记录）",
    "买家收货后反馈问题的时间点，与签收时间对照",
    "商品详情页截图（描述、成色说明与发货时一致）",
)


def _t(dt: datetime | None) -> str:
    if dt is None:
        return "—"
    if dt.tzinfo is None:  # SQLite 取回的是不带时区的 UTC
        dt = dt.replace(tzinfo=ZoneInfo("UTC"))
    return dt.astimezone(TZ).strftime("%Y-%m-%d %H:%M:%S")


def _cell(text: object) -> str:
    return str(text if text not in (None, "") else "—").replace("|", "／").replace("\n", " ")


async def build_evidence(session: AsyncSession, conv: Conversation) -> tuple[str, str]:
    """返回 (markdown, 建议文件名)。"""
    account = await session.get(XyAccount, conv.account_id)
    orders = list(
        (
            await session.execute(
                select(Order)
                .where(
                    Order.account_id == conv.account_id,
                    or_(Order.cid == conv.cid, Order.buyer_id == conv.peer_id)
                    if conv.peer_id
                    else Order.cid == conv.cid,
                )
                .order_by(Order.created_at)
            )
        ).scalars()
    )
    records = (
        list(
            (
                await session.execute(
                    select(DeliveryRecord)
                    .where(DeliveryRecord.order_pk.in_([o.id for o in orders]))
                    .order_by(DeliveryRecord.created_at)
                )
            ).scalars()
        )
        if orders
        else []
    )
    messages = list(
        (
            await session.execute(
                select(ChatMessage)
                .where(ChatMessage.conversation_id == conv.id)
                .order_by(ChatMessage.created_at, ChatMessage.id)
            )
        ).scalars()
    )
    item_id = conv.item_id or next((o.item_id for o in orders if o.item_id), None)
    item_title = next((o.item_title for o in orders if o.item_title), "")
    if item_id and not item_title:
        item = (
            await session.execute(select(MyItem).where(MyItem.account_id == conv.account_id, MyItem.item_id == item_id))
        ).scalar_one_or_none()
        item_title = item.title if item else ""

    seller = (account.nickname or account.remark or account.unb) if account else f"账号 #{conv.account_id}"
    lines = [
        "# 交易举证材料",
        "",
        f"整理时间：{_t(datetime.now(TZ))}（北京时间，以下时间同）",
        "",
        "## 基本信息",
        "",
        f"- 卖家账号：{seller}",
        f"- 买家：{conv.peer_name or '—'}（ID {conv.peer_id or '—'}）",
        f"- 商品：{item_title or '—'}"
        + (f"（ID {item_id}，https://www.goofish.com/item?id={item_id}）" if item_id else ""),
        "",
        "## 订单",
        "",
    ]
    if orders:
        lines += ["| 订单号 | 金额 | 状态 | 下单时间 | 付款时间 | 发货时间 |", "|---|---|---|---|---|---|"]
        for o in orders:
            lines.append(
                f"| {_cell(o.order_id)} | {_cell(f'¥{o.amount:g}' if o.amount is not None else None)} "
                f"| {_cell(ORDER_STATE_LABELS.get(o.status, o.status))} | {_t(o.created_at)} | {_t(o.paid_at)} "
                f"| {_t(o.delivered_at)} |"
            )
    else:
        lines.append("系统中没有与该会话关联的订单。")

    if records:
        lines += ["", "## 发货记录", ""]
        for r in records:
            state = "成功" if r.success else f"失败（{r.error or '未知原因'}）"
            lines.append(
                f"- {_t(r.created_at)} · {state} · 已发送消息：{'是' if r.message_sent else '否'} · "
                f"已在闲鱼确认发货：{'是' if r.consigned else '否'}"
                + (f" · 内容预览：{r.preview}" if r.preview else "")
            )

    lines += ["", f"## 聊天记录（共 {len(messages)} 条，按时间顺序）", ""]
    for m in messages:
        who = "系统" if m.is_system else ("买家" if m.direction == "in" else _SOURCE.get(m.source, "我"))
        text = (m.text or "（非文字消息）").replace("\n", " ")
        lines.append(f"- [{_t(m.created_at)}] {who}：{text}")

    lines += [
        "",
        "## 建议一并准备",
        "",
        *[f"- [ ] {c}" for c in CHECKLIST],
        "",
        "> 以上订单、发货与聊天内容由鱼塘管家根据本地记录整理；聊天记录以闲鱼 App 内为准，提交前请核对。",
    ]
    stamp = datetime.now(TZ).strftime("%Y%m%d")
    return "\n".join(lines) + "\n", f"举证材料-{conv.peer_name or conv.peer_id or conv.id}-{stamp}.md"
