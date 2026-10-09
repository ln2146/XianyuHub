"""启动编排：初始化运行时、注册事件订阅与定时任务。

API 进程与独立 worker 进程共用这里的逻辑：
- setup_runtime()：所有进程都需要（网关、风控守卫、事件订阅）
- start_workers()：只在运行后台任务的进程中调用（调度器、IM 网关）
"""

from loguru import logger

from app.core.config import get_settings
from app.core.events import Topics, bus
from app.domains.account import service as account_service
from app.domains.buyer import scheduling as buyer_scheduling
from app.domains.goods import service as goods_service
from app.domains.message import service as message_service
from app.runtime import close_runtime, get_runtime, init_runtime
from app.workers import scheduler
from app.workers.im_gateway import ImGatewayManager, get_im_manager, set_im_manager


async def setup_runtime(transport=None) -> None:
    await init_runtime(transport)
    rt = get_runtime()
    rt.guard.on_state_change(account_service.on_guard_state_change)
    await account_service.load_guard_states()


async def start_workers() -> None:
    scheduler.add_interval_job("account.keepalive", account_service.keepalive_all, seconds=30 * 60, jitter=300)
    await buyer_scheduling.register_all()
    scheduler.add_interval_job("goods.publish_due", goods_service.publish_due_drafts, seconds=60, jitter=5)
    scheduler.add_cron_job("goods.polish_all", goods_service.polish_all, "30 9 * * *")
    scheduler.start()
    manager = ImGatewayManager(message_service.handle_event)
    set_im_manager(manager)
    bus.subscribe(Topics.ACCOUNT_STATUS_CHANGED, manager.on_account_status)
    await manager.start_all()
    logger.info("后台任务已启动")


async def shutdown() -> None:
    scheduler.shutdown()
    manager = get_im_manager()
    if manager is not None:
        await manager.stop_all()
        set_im_manager(None)
    await message_service.drain()
    await close_runtime()


def workers_enabled() -> bool:
    return get_settings().run_workers_in_api
