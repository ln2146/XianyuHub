from datetime import UTC, datetime

import respx

from app.core.db import session_factory
from app.domains.message.models import ChatMessage, Conversation
from app.domains.order.models import DeliveryRecord, Order, OrderState
from tests.test_accounts import COOKIES, mock_probe


@respx.mock
async def test_conversation_evidence_pack(admin_client):
    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    async with session_factory()() as s:
        conv = Conversation(account_id=acc["id"], cid="c9", peer_id="3300", peer_name="买家A", item_id="900")
        s.add(conv)
        await s.flush()
        t = datetime(2026, 10, 1, 4, 0, 5, tzinfo=UTC)  # 北京时间 12:00:05
        for direction, source, text in [
            ("in", "buyer", "还在吗"),
            ("out", "auto_keyword", "在的～商品还在"),
            ("in", "buyer", "收到了，屏幕有划痕，退一半吧"),
        ]:
            s.add(
                ChatMessage(
                    conversation_id=conv.id,
                    account_id=acc["id"],
                    direction=direction,
                    source=source,
                    text=text,
                    created_at=t,
                )
            )
        order = Order(
            account_id=acc["id"],
            order_id="o-77",
            item_id="900",
            item_title="iPhone 13 128G",
            buyer_id="3300",
            status=OrderState.COMPLETED,
            amount=1999,
            paid_at=t,
            delivered_at=t,
        )
        s.add(order)
        await s.flush()
        s.add(
            DeliveryRecord(
                order_pk=order.id,
                preview="SN: F2L****",
                mode="send_then_confirm",
                message_sent=True,
                consigned=True,
                success=True,
            )
        )
        await s.commit()
        conv_id = conv.id

    r = await admin_client.get(f"/api/v1/messages/conversations/{conv_id}/evidence")
    assert r.status_code == 200, r.text
    md = r.json()["markdown"]
    assert "# 交易举证材料" in md and "买家A（ID 3300）" in md and "iPhone 13 128G（ID 900" in md
    assert "| o-77 | ¥1999 | 已完成 |" in md and "2026-10-01 12:00:05" in md
    assert "已在闲鱼确认发货：是" in md and "SN: F2L****" in md
    assert "我（关键词自动回复）：在的～商品还在" in md and "买家：收到了，屏幕有划痕，退一半吧" in md
    assert "共 3 条" in md and "打包、封箱到交给快递的完整视频" in md
    assert r.json()["filename"].startswith("举证材料-买家A-")

    assert (await admin_client.get("/api/v1/messages/conversations/999999/evidence")).status_code == 404
