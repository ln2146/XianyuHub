"""启动编排：初始化运行时、注册事件订阅与定时任务。

API 进程与独立 worker 进程共用这里的逻辑：
- setup_runtime()：所有进程都需要（网关、风控守卫、事件订阅）
- start_workers()：只在运行后台任务的进程中调用（调度器、IM 网关）
"""

from loguru import logger

from app.core.config import get_settings
from app.domains.account import service as account_service
from app.runtime import close_runtime, get_runtime, init_runtime
from app.workers import scheduler


async def setup_runtime(transport=None) -> None:
    await init_runtime(transport)
    rt = get_runtime()
    rt.guard.on_state_change(account_service.on_guard_state_change)
    await account_service.load_guard_states()


async def start_workers() -> None:
    scheduler.add_interval_job("account.keepalive", account_service.keepalive_all, seconds=30 * 60, jitter=300)
    scheduler.start()
    logger.info("后台任务已启动")


async def shutdown() -> None:
    scheduler.shutdown()
    await close_runtime()


def workers_enabled() -> bool:
    return get_settings().run_workers_in_api
