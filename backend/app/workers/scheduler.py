"""定时任务调度器（APScheduler）。

单机模式下随 API 进程启动；多进程部署时由独立的 worker 进程运行（python -m app.workers.main）。
部署多个 worker 时，周期任务和 cron 任务通过 Redis 锁保证同一轮只在一个进程里执行。
"""

import functools
from collections.abc import Awaitable, Callable
from datetime import datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.date import DateTrigger
from loguru import logger

_scheduler: AsyncIOScheduler | None = None


def get_scheduler() -> AsyncIOScheduler:
    global _scheduler
    if _scheduler is None:
        _scheduler = AsyncIOScheduler(timezone="Asia/Shanghai")
    return _scheduler


def once_per_cluster(job_id: str, fn: Callable[..., Awaitable[None]], ttl: int) -> Callable[..., Awaitable[None]]:
    """多进程部署时，同一任务在 ttl 秒内只由抢到锁的那个进程执行。

    锁不在任务结束时释放，而是等它过期：各 worker 的调度时间有随机抖动，提前释放会让另一个进程紧接着再跑一遍。"""

    @functools.wraps(fn)
    async def run(*args: object) -> None:
        from app.core.cluster import get_cluster

        cluster = get_cluster()
        if cluster is not None:
            try:
                token = await cluster.try_lock(f"job:{job_id}", ttl)
            except Exception as e:  # noqa: BLE001  Redis 故障时照常执行：发货等关键步骤本身有数据库层面的防重
                logger.warning("调度锁获取失败 job={} err={}，本进程照常执行", job_id, e)
                token = "local"
            if token is None:
                logger.debug("任务 {} 本轮已由其他进程执行，跳过", job_id)
                return
        await fn(*args)

    return run


def add_interval_job(job_id: str, fn: Callable[[], Awaitable[None]], seconds: int, *, jitter: int = 30) -> None:
    # 锁住半个周期：盖住其他进程带抖动的同一轮触发，又不会挡到本进程的下一轮
    get_scheduler().add_job(
        once_per_cluster(job_id, fn, max(seconds // 2, 1)),
        "interval",
        seconds=seconds,
        id=job_id,
        replace_existing=True,
        jitter=jitter,
        max_instances=1,
        coalesce=True,
    )


def add_cron_job(job_id: str, fn: Callable[..., Awaitable[None]], cron: str, *, args: list | None = None) -> None:
    get_scheduler().add_job(
        once_per_cluster(job_id, fn, 50),  # cron 最小粒度是分钟：同一分钟的触发只执行一次
        CronTrigger.from_crontab(cron, timezone="Asia/Shanghai"),
        id=job_id,
        args=args or [],
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )


def add_date_job(
    job_id: str, fn: Callable[..., Awaitable[None]], run_at: datetime, *, args: list | None = None
) -> None:
    """在指定时间运行一次（如退避重试）；同 id 的旧任务会被替换。"""
    get_scheduler().add_job(
        fn,
        DateTrigger(run_date=run_at),
        id=job_id,
        args=args or [],
        replace_existing=True,
        misfire_grace_time=600,
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
