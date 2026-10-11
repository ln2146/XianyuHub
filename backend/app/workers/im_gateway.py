"""IM 网关：为每个活跃账号维持一条闲鱼 IM 长连接。

- 收到的事件交给 message 域的 handle_event
- 所有发送都经过风控守卫（消息令牌桶）
- 账号状态变化时自动启停连接
"""

import asyncio
import contextlib
import time
from collections.abc import Awaitable, Callable
from typing import Any, Protocol

from loguru import logger
from sqlalchemy import select

from app.core.db import session_factory
from app.goofish.dto import ImEvent
from app.goofish.gateway import account_key
from app.goofish.guard.guard import AccountState
from app.goofish.guard.policy import Action
from app.goofish.protocol.lwp import LwpClient
from app.runtime import get_runtime

EventHandler = Callable[[int, ImEvent], Awaitable[None]]
# 意外断线超过这个时间还没重连上：通知卖家（期间收不到买家消息，自动回复 / 发货都会停）
DISCONNECT_ALERT_SECONDS = 300


class ImClient(Protocol):
    connected: asyncio.Event

    async def run_forever(self) -> None: ...

    async def stop(self) -> None: ...

    async def send_text(self, cid: str, to_id: str, text: str) -> Any: ...

    async def send_image(self, cid: str, to_id: str, url: str, width: int, height: int) -> Any: ...


ClientFactory = Callable[..., Awaitable[ImClient]]


async def default_client_factory(account_id: int, on_event: EventHandler, on_status) -> ImClient:  # noqa: ANN001
    from app.domains.account.models import XyAccount

    rt = get_runtime()
    async with session_factory()() as s:
        acc = await s.get(XyAccount, account_id)
        assert acc is not None
        unb, device_id = acc.unb, acc.device_id

    async def token_provider() -> str:
        return await rt.gateway.get_im_token(account_id, device_id)

    async def _on_event(ev: ImEvent) -> None:
        await on_event(account_id, ev)

    async def _on_status(status: str, detail: str | None) -> None:
        await on_status(account_id, status, detail)

    return LwpClient(
        my_id=unb,
        device_id=device_id,
        cookie_header=await rt.gateway.cookie_header(account_id),
        token_provider=token_provider,
        on_event=_on_event,
        on_status=_on_status,
    )


class ImGatewayManager:
    def __init__(self, on_event: EventHandler, client_factory: ClientFactory = default_client_factory) -> None:
        self._on_event = on_event
        self._factory = client_factory
        self._clients: dict[int, ImClient] = {}
        self._tasks: dict[int, asyncio.Task] = {}
        self.status: dict[int, dict[str, Any]] = {}
        self._watchers: dict[int, asyncio.Task] = {}
        self.alert_after = DISCONNECT_ALERT_SECONDS

    async def _on_status(self, account_id: int, status: str, detail: str | None) -> None:
        self.status[account_id] = {"status": status, "detail": detail, "at": time.time()}
        if status == "disconnected" and not (account_id in self._watchers and not self._watchers[account_id].done()):
            self._watchers[account_id] = asyncio.create_task(self._alert_if_still_down(account_id))

    async def _alert_if_still_down(self, account_id: int) -> None:
        await asyncio.sleep(self.alert_after)
        if account_id not in self._clients or self.is_connected(account_id):
            return  # 已重连，或是主动停掉的（掉登录 / 停用另有通知）
        from app.domains.account.models import XyAccount
        from app.notify.senders import Notification
        from app.notify.service import NotifyEvents, notify

        async with session_factory()() as s:
            acc = await s.get(XyAccount, account_id)
            if acc is None:
                return
            owner_id, name = acc.owner_id, acc.nickname or acc.unb
        detail = (self.status.get(account_id) or {}).get("detail") or ""
        await notify(
            owner_id,
            Notification(
                event=NotifyEvents.ACCOUNT_RISK,
                title=f"⚠️ 账号 {name} 的消息连接已断开",
                content=f"已断开超过 {self.alert_after // 60} 分钟，系统仍在自动重连。期间收不到买家消息，"
                "自动回复和自动发货都会暂停。如果长时间无法恢复，请到「账号」页检查登录状态。"
                + (f"\n原因：{detail[:120]}" if detail else ""),
            ),
            dedupe_key=f"im_down:{account_id}",
        )

    async def start_account(self, account_id: int) -> None:
        if account_id in self._tasks and not self._tasks[account_id].done():
            return
        client = await self._factory(account_id, self._on_event, self._on_status)
        self._clients[account_id] = client
        self._tasks[account_id] = asyncio.create_task(client.run_forever(), name=f"im-{account_id}")
        self.status[account_id] = {"status": "connecting", "detail": None, "at": time.time()}
        logger.info("IM 连接启动 account={}", account_id)

    async def stop_account(self, account_id: int) -> None:
        watcher = self._watchers.pop(account_id, None)
        if watcher:
            watcher.cancel()
        client = self._clients.pop(account_id, None)
        task = self._tasks.pop(account_id, None)
        if client:
            await client.stop()
        if task:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        self.status[account_id] = {"status": "stopped", "detail": None, "at": time.time()}

    async def start_all(self) -> None:
        from app.domains.account.models import XyAccount

        async with session_factory()() as s:
            ids = [a for (a,) in await s.execute(select(XyAccount.id).where(XyAccount.status == AccountState.ACTIVE))]
        for account_id in ids:
            try:
                await self.start_account(account_id)
            except Exception as e:  # noqa: BLE001
                logger.warning("IM 启动失败 account={} err={}", account_id, e)

    async def stop_all(self) -> None:
        for account_id in list(self._clients):
            await self.stop_account(account_id)

    async def on_account_status(self, payload: dict[str, Any]) -> None:
        account_id = payload.get("account_id")
        if account_id is None:
            return
        if payload.get("state") == AccountState.ACTIVE:
            if payload.get("restart"):
                await self.stop_account(account_id)
            await self.start_account(account_id)
        elif payload.get("state") in (AccountState.NEED_LOGIN, AccountState.DISABLED, AccountState.CIRCUIT_OPEN):
            await self.stop_account(account_id)

    def is_connected(self, account_id: int) -> bool:
        client = self._clients.get(account_id)
        return bool(client and client.connected.is_set())

    async def send_text(self, account_id: int, cid: str, to_id: str, text: str) -> None:
        client = self._clients.get(account_id)
        if client is None or not client.connected.is_set():
            raise ConnectionError("该账号 IM 未连接")
        await get_runtime().guard.run(
            account_key(account_id), Action.SEND_MESSAGE, lambda: client.send_text(cid, to_id, text)
        )

    async def send_image(self, account_id: int, cid: str, to_id: str, url: str, width: int, height: int) -> None:
        client = self._clients.get(account_id)
        if client is None or not client.connected.is_set():
            raise ConnectionError("该账号 IM 未连接")
        await get_runtime().guard.run(
            account_key(account_id), Action.SEND_MESSAGE, lambda: client.send_image(cid, to_id, url, width, height)
        )


_manager: ImGatewayManager | None = None


async def im_status_snapshot() -> dict[str, Any] | None:
    """{account_id(str): {status, detail, at, connected}}；本进程没有 IM 网关时向 Worker 查询，都没有返回 None。"""
    manager = get_im_manager()
    if manager is not None:
        return {str(k): {**v, "connected": manager.is_connected(k)} for k, v in manager.status.items()}
    from app.core.cluster import ClusterUnavailable, get_cluster

    cluster = get_cluster()
    if cluster is None:
        return None
    try:
        return await cluster.call("im.status", {}, timeout=5)
    except (ClusterUnavailable, RuntimeError):
        return None


def get_im_manager() -> ImGatewayManager | None:
    return _manager


def set_im_manager(manager: ImGatewayManager | None) -> None:
    global _manager
    _manager = manager
