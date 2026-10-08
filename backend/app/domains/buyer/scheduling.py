"""选品任务与调度器的同步。"""

from sqlalchemy import select

from app.core.db import session_factory
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


async def register_all() -> None:
    global _enabled
    _enabled = True
    async with session_factory()() as s:
        for task in (await s.execute(select(MonitorTask).where(MonitorTask.enabled.is_(True)))).scalars():
            sync_task(task)
