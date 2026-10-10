"""启动编排：初始化运行时、注册事件订阅与定时任务。

进程角色（PROCESS_ROLE）：
- all（默认）：单进程，API 内同时运行调度器和 IM 网关（RUN_WORKERS_IN_API=true）
- api：只提供 HTTP 接口；需要 IM 的操作通过 Redis 集群桥交给 Worker
- worker：运行调度器、IM 网关和订单处理（python -m app.workers.main）
"""

from typing import Any

from loguru import logger

from app.core.cluster import Cluster, get_cluster, set_cluster
from app.core.config import get_settings
from app.core.events import Topics, bus
from app.core.realtime import hub
from app.domains.account import service as account_service
from app.domains.buyer import scheduling as buyer_scheduling
from app.domains.buyer import watch as buyer_watch
from app.domains.goods import service as goods_service
from app.domains.message import service as message_service
from app.domains.order import service as order_service
from app.domains.system import llm as llm_service
from app.runtime import close_runtime, get_runtime, init_runtime
from app.workers import scheduler
from app.workers.im_gateway import ImGatewayManager, get_im_manager, im_status_snapshot, set_im_manager


def role() -> str:
    return get_settings().process_role


def runs_workers() -> bool:
    """本进程是否负责后台任务（调度器、IM 网关、订单事件处理）。"""
    return role() == "worker" or (role() == "all" and get_settings().run_workers_in_api)


async def _on_remote_event(topic: str, payload: dict[str, Any]) -> None:
    if topic == Topics.ACCOUNT_STATUS_CHANGED and payload.get("account_id") is not None:
        await account_service.reload_guard_state(payload["account_id"])
    if topic == Topics.LLM_CONFIG_CHANGED:
        # 其他进程改了模型配置，本进程重新装载
        from app.domains.system import llm as llm_service

        await llm_service.apply_active_config()
    await bus.publish(topic, payload, remote=True)


async def _on_remote_hub(message: dict[str, Any]) -> None:
    await hub.publish(
        message.get("event", ""),
        message.get("data") or {},
        account_id=message.get("account_id"),
        user_id=message.get("user_id"),
        remote=True,
    )


async def _setup_cluster() -> None:
    if role() == "all":
        return
    rt = get_runtime()
    if rt.redis is None:
        raise RuntimeError(f"PROCESS_ROLE={role()} 需要配置 REDIS_URL")
    cluster = Cluster(rt.redis, role())
    cluster.on_event(_on_remote_event)
    cluster.on_hub(_on_remote_hub)
    bus.bridge = cluster
    hub.bridge = cluster
    set_cluster(cluster)
    await cluster.start()


async def setup_runtime(transport=None) -> None:
    await init_runtime(transport)
    rt = get_runtime()
    rt.guard.on_state_change(account_service.on_guard_state_change)
    await account_service.load_guard_states()
    if role() in ("all", "worker"):
        bus.subscribe(Topics.ORDER_STATUS_CHANGED, order_service.on_order_event)
    await llm_service.apply_active_config()
    await _setup_cluster()


async def start_workers() -> None:
    scheduler.add_interval_job("account.keepalive", account_service.keepalive_all, seconds=30 * 60, jitter=300)
    scheduler.add_interval_job("guard.heal", get_runtime().guard.heal_expired, seconds=60, jitter=5)
    await buyer_scheduling.register_all()
    scheduler.add_interval_job("buyer.price_watch", buyer_watch.check_due_watches, seconds=5 * 60, jitter=30)
    scheduler.add_interval_job("goods.publish_due", goods_service.publish_due_drafts, seconds=60, jitter=5)
    scheduler.add_cron_job("goods.polish_all", goods_service.polish_all, "30 9 * * *")
    scheduler.add_interval_job("order.retry_failed", order_service.retry_failed, seconds=60, jitter=10)
    scheduler.add_interval_job("order.remind_unshipped", order_service.remind_unshipped, seconds=30 * 60, jitter=60)
    scheduler.add_interval_job("order.sync", order_service.sync_all_auto_delivery, seconds=10 * 60, jitter=60)
    scheduler.start()
    manager = ImGatewayManager(message_service.handle_event)
    set_im_manager(manager)
    bus.subscribe(Topics.ACCOUNT_STATUS_CHANGED, manager.on_account_status)
    cluster = get_cluster()
    if cluster is not None:
        cluster.register("im.send", message_service.rpc_im_send)

        async def _status(_: dict[str, Any]) -> dict[str, Any] | None:
            return await im_status_snapshot()

        cluster.register("im.status", _status)

        async def _jobs(_: dict[str, Any]) -> list[dict[str, Any]]:
            return scheduler.jobs_snapshot()

        cluster.register("system.jobs", _jobs)
    await manager.start_all()
    logger.info("后台任务已启动")


async def shutdown() -> None:
    scheduler.shutdown()
    manager = get_im_manager()
    if manager is not None:
        await manager.stop_all()
        set_im_manager(None)
    await message_service.drain()
    cluster = get_cluster()
    if cluster is not None:
        await cluster.stop()
        set_cluster(None)
    bus.bridge = None
    hub.bridge = None
    await close_runtime()


def workers_enabled() -> bool:
    return runs_workers() and role() == "all"
