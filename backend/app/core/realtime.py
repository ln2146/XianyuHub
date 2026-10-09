"""前端实时推送（WebSocket）：按账号访问权限把事件推给已连接的管理台用户。"""

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any

from fastapi import WebSocket


@dataclass(eq=False)
class _Conn:
    ws: WebSocket
    user_id: int
    account_ids: set[int] | None  # None 表示管理员，可见全部


class RealtimeHub:
    def __init__(self) -> None:
        self._conns: set[_Conn] = set()
        self._lock = asyncio.Lock()

    async def add(self, ws: WebSocket, user_id: int, account_ids: set[int] | None) -> _Conn:
        conn = _Conn(ws, user_id, account_ids)
        async with self._lock:
            self._conns.add(conn)
        return conn

    async def remove(self, conn: _Conn) -> None:
        async with self._lock:
            self._conns.discard(conn)

    @property
    def size(self) -> int:
        return len(self._conns)

    async def publish(
        self, event: str, data: dict[str, Any], *, account_id: int | None = None, user_id: int | None = None
    ) -> None:
        payload = json.dumps({"event": event, "data": data}, ensure_ascii=False, default=str)
        for conn in list(self._conns):
            if user_id is not None and conn.user_id != user_id:
                continue
            if account_id is not None and conn.account_ids is not None and account_id not in conn.account_ids:
                continue
            try:
                await conn.ws.send_text(payload)
            except Exception:  # noqa: BLE001
                with contextlib.suppress(Exception):
                    await self.remove(conn)


hub = RealtimeHub()
