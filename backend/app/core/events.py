"""领域事件总线。

单机模式使用进程内实现；多进程部署时可替换为 Redis Streams 实现（接口一致）。
"""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

Handler = Callable[[dict[str, Any]], Awaitable[None]]


class Topics:
    CHAT_MESSAGE_RECEIVED = "chat.message.received"
    ORDER_STATUS_CHANGED = "order.status.changed"
    ORDER_PAID = "order.paid"
    MARKET_ITEM_FOUND = "market.item.found"
    MARKET_ITEM_RECOMMENDED = "market.item.recommended"
    ACCOUNT_RISK_DETECTED = "account.risk.detected"
    ACCOUNT_STATUS_CHANGED = "account.status.changed"
    ITEM_PUBLISHED = "item.published"
    BUYER_TASK_CHANGED = "buyer.task.changed"
    DELIVERY_FAILED = "delivery.failed"
    LLM_CONFIG_CHANGED = "llm.config.changed"


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[str, list[Handler]] = defaultdict(list)
        self._tasks: set[asyncio.Task] = set()
        self.bridge: Any = None  # app.core.cluster.Cluster，分离部署时设置

    def subscribe(self, topic: str, handler: Handler) -> None:
        self._handlers[topic].append(handler)

    def clear(self) -> None:
        self._handlers.clear()
        self.bridge = None

    async def publish(self, topic: str, payload: dict[str, Any], *, remote: bool = False) -> None:
        """remote=True 表示事件来自其他进程，只在本进程分发，不再转发。"""
        if self.bridge is not None and not remote:
            try:
                await self.bridge.broadcast_event(topic, payload)
            except Exception:  # noqa: BLE001
                logger.exception("跨进程事件转发失败 topic={}", topic)
        for handler in list(self._handlers.get(topic, [])):
            task = asyncio.create_task(self._run(topic, handler, payload))
            self._tasks.add(task)
            task.add_done_callback(self._tasks.discard)

    async def _run(self, topic: str, handler: Handler, payload: dict[str, Any]) -> None:
        try:
            await handler(payload)
        except Exception:  # noqa: BLE001
            logger.exception("事件处理失败 topic={} handler={}", topic, getattr(handler, "__name__", handler))

    async def drain(self) -> None:
        """等待所有已派发的处理器完成（测试与优雅退出使用）。"""
        while self._tasks:
            await asyncio.gather(*list(self._tasks), return_exceptions=True)


bus = EventBus()
