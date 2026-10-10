"""选品任务与调度器的同步。"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.core.db import session_factory
from app.core.events import Topics, bus
from app.domains.buyer.models import MonitorTask
from app.domains.buyer.pipeline import run_task
from app.workers import scheduler

_enabled = False


def job_id(task_id: int) -> str:
    return f"buyer.task.{task_id}"


def retry_job_id(task_id: int) -> str:
    return f"buyer.task.{task_id}.retry"


def sync_task(task: MonitorTask) -> None:
    if not _enabled:
        return
    if task.enabled:
        scheduler.add_cron_job(job_id(task.id), run_task, task.cron, args=[task.id])
    else:
        scheduler.remove_job(job_id(task.id))
    if task.enabled and task.retry_at is not None:
        # 风控退避重试；进程重启时已过期的重试稍后补跑
        at = task.retry_at if task.retry_at.tzinfo else task.retry_at.replace(tzinfo=UTC)
        at = max(at, datetime.now(UTC) + timedelta(seconds=5))
        scheduler.add_date_job(retry_job_id(task.id), run_task, at, args=[task.id])
    else:
        scheduler.remove_job(retry_job_id(task.id))


def remove_task(task_id: int) -> None:
    if _enabled:
        scheduler.remove_job(job_id(task_id))
        scheduler.remove_job(retry_job_id(task_id))


async def on_task_changed(payload: dict) -> None:
    """任务增删改（可能来自 API 进程）后，从数据库重新同步该任务的调度。"""
    if not _enabled:
        return
    task_id = payload.get("task_id")
    async with session_factory()() as s:
        task = await s.get(MonitorTask, task_id) if task_id is not None else None
    if task is None:
        remove_task(task_id)
    else:
        sync_task(task)


async def register_all() -> None:
    global _enabled
    _enabled = True
    bus.subscribe(Topics.BUYER_TASK_CHANGED, on_task_changed)
    async with session_factory()() as s:
        for task in (await s.execute(select(MonitorTask).where(MonitorTask.enabled.is_(True)))).scalars():
            sync_task(task)
