from datetime import timedelta

from app.core.db import session_factory
from app.domains.account.models import XyAccount
from app.domains.order.models import Order, OrderState
from app.domains.system.dashboard import _today_start


async def test_dashboard_counts_actual_payments_in_beijing_day(admin_client):
    start = _today_start()
    async with session_factory()() as session:
        account = XyAccount(owner_id=1, unb="payment-test", device_id="payment-test")
        session.add(account)
        await session.flush()
        cases = [
            # 昨日创建，今日付款：应计入。
            ("yesterday-created", start - timedelta(days=1), start + timedelta(hours=1), 100, OrderState.DELIVERED),
            # 今日同步/创建，但昨日付款：不计入。
            ("old-payment", start + timedelta(hours=2), start - timedelta(seconds=1), 200, OrderState.COMPLETED),
            # 边界：北京时间零点计入，下一天零点不计入。
            ("at-start", start, start, 30, OrderState.PAID),
            ("next-day", start, start + timedelta(days=1), 400, OrderState.PAID),
            # 退款订单仍属于今日支付流水；不伪装成净收入。
            ("refunded", start, start + timedelta(hours=3), 50, OrderState.REFUNDED),
            ("pending", start, None, 60, OrderState.PENDING_PAY),
            ("unknown-paid-time", start, None, 70, OrderState.DELIVERED),
        ]
        for order_id, created, paid, amount, state in cases:
            session.add(
                Order(
                    account_id=account.id,
                    order_id=order_id,
                    created_at=created,
                    paid_at=created,
                    actual_paid_at=paid,
                    amount=amount,
                    status=state,
                )
            )
        # 未授权账号的付款不计入当前用户。
        from app.domains.system.models import Role, User

        other = User(username="outside", password_hash="unused-test-hash", role=Role.MEMBER)
        session.add(other)
        await session.flush()
        other_account = XyAccount(owner_id=other.id, unb="outside-payment", device_id="outside-payment")
        session.add(other_account)
        await session.flush()
        session.add(
            Order(
                account_id=other_account.id,
                order_id="outside-order",
                actual_paid_at=start,
                amount=999,
                status=OrderState.PAID,
            )
        )
        await session.commit()
    dash = (await admin_client.get("/api/v1/dashboard")).json()
    today = dash["today"]
    # 近 7 天趋势：最后一天即今天，口径与今日统计一致；昨日付款落在前一天
    assert len(dash["trend"]) == 7
    assert dash["trend"][-1]["orders"] == 4 and dash["trend"][-1]["amount"] == 1179
    assert dash["trend"][-2]["orders"] == 1 and dash["trend"][-2]["amount"] == 200
    # 待发货：已付款未发出（PAID 三笔，含 outside）
    assert dash["to_ship"] == 3
    # admin可以访问所有账号，统计应包含outside；普通用户隔离另测。
    assert today["paid_orders"] == 4 and today["paid_amount"] == 1179
    assert today["orders"]["refunded"] == 1
    assert "退款未扣除" in today["payment_basis"]


async def test_payment_stats_do_not_include_ungranted_accounts(admin_client):
    from app.core.security import hash_password
    from app.domains.system.models import Role, User

    async with session_factory()() as session:
        member = User(username="member-payment", password_hash=hash_password("member-payment-pass"), role=Role.MEMBER)
        session.add(member)
        await session.flush()
        own = XyAccount(owner_id=member.id, unb="own", device_id="own")
        other = XyAccount(owner_id=1, unb="admin-only", device_id="admin-only")
        session.add_all([own, other])
        await session.flush()
        for account, amount in [(own, 10), (other, 1000)]:
            session.add(
                Order(
                    account_id=account.id,
                    order_id=f"paid-{account.id}",
                    actual_paid_at=_today_start(),
                    amount=amount,
                    status=OrderState.PAID,
                )
            )
        await session.commit()
    login = await admin_client.post(
        "/api/v1/auth/login", json={"username": "member-payment", "password": "member-payment-pass"}
    )
    response = await admin_client.get(
        "/api/v1/dashboard", headers={"Authorization": f"Bearer {login.json()['access_token']}"}
    )
    assert response.status_code == 200
    assert response.json()["today"]["paid_orders"] == 1
    assert response.json()["today"]["paid_amount"] == 10
