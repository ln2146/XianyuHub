"""定时任务调度器（APScheduler）。

单机模式下随 API 进程启动；多进程部署时由独立的 worker 进程运行（python -m app.workers.main）。
"""

from collections.abc import Awaitable, Callable

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from loguru import logger

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


def add_interval_job(job_id: str, fn: Callable[[], Awaitable[None]], seconds: int, *, jitter: int = 30) -> None:
    get_scheduler().add_job(
        fn, "interval", seconds=seconds, id=job_id, replace_existing=True, jitter=jitter, max_instances=1, coalesce=True
    )


def add_cron_job(job_id: str, fn: Callable[..., Awaitable[None]], cron: str, *, args: list | None = None) -> None:
    get_scheduler().add_job(
        fn,
        CronTrigger.from_crontab(cron, timezone="Asia/Shanghai"),
        id=job_id,
        args=args or [],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )


def remove_job(job_id: str) -> None:
    sched = get_scheduler()
    if sched.get_job(job_id):
        sched.remove_job(job_id)


def start() -> None:
    sched = get_scheduler()
    if not sched.running:
        sched.start()
        logger.info("调度器已启动")


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None and _scheduler.running:
        _scheduler.shutdown(wait=False)
    _scheduler = None
