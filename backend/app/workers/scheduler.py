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


def jobs_snapshot() -> list[dict]:
    sched = get_scheduler()
    if not sched.running:
        return []
    return [
        {"id": j.id, "next_run": j.next_run_time.isoformat() if j.next_run_time else None} for j in sched.get_jobs()
    ]


async def jobs_anywhere() -> list[dict]:
    """本进程的调度任务；分离部署的 API 进程向 Worker 查询。"""
    local = jobs_snapshot()
    if local:
        return local
    from app.core.cluster import ClusterUnavailable, get_cluster

    cluster = get_cluster()
    if cluster is None:
        return []
    try:
        return await cluster.call("system.jobs", {}, timeout=5) or []
    except (ClusterUnavailable, RuntimeError):
        return []


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
