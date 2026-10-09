"""选品任务与调度器的同步。"""

from sqlalchemy import select

from app.core.db import session_factory
from app.core.events import Topics, bus
from app.domains.buyer.models import MonitorTask
from app.domains.buyer.pipeline import run_task
from app.workers import scheduler

_enabled = False


def job_id(task_id: int) -> str:
    return f"buyer.task.{task_id}"


def sync_task(task: MonitorTask) -> None:
    if not _enabled:
        return
    if task.enabled:
        scheduler.add_cron_job(job_id(task.id), run_task, task.cron, args=[task.id])
    else:
        scheduler.remove_job(job_id(task.id))


def remove_task(task_id: int) -> None:
    if _enabled:
        scheduler.remove_job(job_id(task_id))


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
