"""数据看板：账号健康、消息 / 订单 / 选品统计、风控事件、系统状态。"""

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import APIRouter
from sqlalchemy import func, select

from app.core.deps import CurrentUser, SessionDep
from app.domains.account.models import RiskEvent, XyAccount
from app.domains.account.service import accessible_account_ids
from app.domains.buyer.models import MonitorTask, TaskResult
from app.domains.message.models import ChatMessage
from app.domains.order.models import Order, OrderState
from app.goofish.gateway import account_key
from app.intelligence.llm import get_llm
from app.runtime import get_runtime
from app.workers import scheduler
from app.workers.im_gateway import get_im_manager

router = APIRouter(tags=["dashboard"])


def _today_start() -> datetime:
    # 以北京时间零点为界
    now = datetime.now(UTC) + timedelta(hours=8)
    return now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(hours=8)


@router.get("/dashboard")
async def dashboard(user: CurrentUser, session: SessionDep) -> dict[str, Any]:
    ids = await accessible_account_ids(session, user)
    acc_stmt = select(XyAccount)
    if ids is not None:
        acc_stmt = acc_stmt.where(XyAccount.id.in_(ids))
    accounts = list((await session.execute(acc_stmt)).scalars())
    acc_ids = [a.id for a in accounts]
    guard = get_runtime().guard
    manager = get_im_manager()
    since = _today_start()

    msg_rows = await session.execute(
        select(ChatMessage.source, func.count())
        .where(ChatMessage.account_id.in_(acc_ids), ChatMessage.created_at >= since)
        .group_by(ChatMessage.source)
    )
    messages = {k: v for k, v in msg_rows}

    order_rows = await session.execute(
        select(Order.status, func.count(), func.coalesce(func.sum(Order.amount), 0))
        .where(Order.account_id.in_(acc_ids), Order.created_at >= since)
        .group_by(Order.status)
    )
    orders: dict[str, int] = {}
    gmv = 0.0
    for st, n, amount in order_rows:
        orders[st] = n
        if st not in (OrderState.PENDING_PAY, OrderState.CLOSED, OrderState.REFUNDED):
            gmv += float(amount or 0)
    pending_manual = (
        await session.execute(
            select(func.count())
            .select_from(Order)
            .where(
                Order.account_id.in_(acc_ids),
                Order.status.in_([OrderState.MANUAL, OrderState.RISK_HOLD, OrderState.DELIVER_FAILED]),
            )
        )
    ).scalar_one()

    task_ids = [t for (t,) in await session.execute(select(MonitorTask.id).where(MonitorTask.owner_id == user.id))]
    rec_rows = await session.execute(
        select(TaskResult.verdict, func.count())
        .where(TaskResult.task_id.in_(task_ids), TaskResult.created_at >= since)
        .group_by(TaskResult.verdict)
    )
    radar = {(k or "filtered"): v for k, v in rec_rows}

    risk_rows = await session.execute(
        select(RiskEvent)
        .where(RiskEvent.account_id.in_(acc_ids), RiskEvent.created_at >= datetime.now(UTC) - timedelta(days=7))
        .order_by(RiskEvent.id.desc())
        .limit(20)
    )

    return {
        "accounts": [
            {
                "id": a.id,
                "nickname": a.nickname or a.unb,
                "status": guard.runtime(account_key(a.id)).state,
                "health": guard.runtime(account_key(a.id)).health,
                "im_connected": bool(manager and manager.is_connected(a.id)),
                "auto_reply": a.get_settings().auto_reply,
                "auto_delivery": a.get_settings().auto_delivery,
            }
            for a in accounts
        ],
        "today": {
            "messages_in": messages.get("buyer", 0),
            "messages_auto": sum(messages.get(k, 0) for k in ("auto_keyword", "auto_ai", "auto_default")),
            "messages_manual": messages.get("web_manual", 0) + messages.get("seller_app", 0),
            "deliveries": messages.get("delivery", 0),
            "orders": orders,
            "gmv": round(gmv, 2),
            "radar": radar,
        },
        "pending_manual_orders": pending_manual,
        "monitor_tasks": len(task_ids),
        "risk_events": [
            {
                "id": r.id,
                "account_id": r.account_id,
                "punish_url": r.punish_url,
                "state": r.state,
                "reason": r.reason,
                "created_at": r.created_at,
                "resolved": r.resolved_at is not None,
            }
            for r in risk_rows.scalars()
        ],
        "system": {
            "llm": get_llm().status(),
            "im_running": manager is not None,
            "jobs": [
                {"id": j.id, "next_run": j.next_run_time}
                for j in (scheduler.get_scheduler().get_jobs() if scheduler.get_scheduler().running else [])
            ],
        },
    }
