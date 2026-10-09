"""列表分页：总数通过响应头 X-Total-Count 返回（不改变列表响应结构）。"""

from fastapi import Response
from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

TOTAL_HEADER = "X-Total-Count"


async def count_total(session: AsyncSession, stmt: Select) -> int:
    sub = stmt.order_by(None).limit(None).offset(None).subquery()
    return (await session.execute(select(func.count()).select_from(sub))).scalar_one()


async def set_total(response: Response | None, session: AsyncSession, stmt: Select) -> None:
    if response is not None:
        response.headers[TOTAL_HEADER] = str(await count_total(session, stmt))
