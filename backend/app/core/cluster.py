"""多进程部署的跨进程桥（Redis Pub/Sub）。

单机模式（PROCESS_ROLE=all）不启用。API 与 Worker 分离部署时：
- 领域事件：一个进程 publish 的事件同步投递到其他进程的订阅者
- 实时推送：Worker 产生的消息推送转发给连着 API 进程的浏览器
- RPC：API 进程把需要 IM 长连接的操作（发消息、查询连接状态）交给 Worker 执行
- 分布式锁：同一选品任务不会在两个进程里同时运行
"""

import asyncio
import contextlib
import json
import uuid
from collections.abc import Awaitable, Callable
from typing import Any

from loguru import logger

CHANNEL = "xyh:cluster"
Handler = Callable[[dict[str, Any]], Awaitable[Any]]


class ClusterUnavailable(Exception):
    pass


class Cluster:
    def __init__(self, redis, role: str) -> None:  # redis.asyncio.Redis
        self.redis = redis
        self.role = role
        self.origin = f"{role}-{uuid.uuid4().hex[:8]}"
        self._event_sink: Callable[[str, dict[str, Any]], Awaitable[None]] | None = None
        self._hub_sink: Callable[[dict[str, Any]], Awaitable[None]] | None = None
        self._rpc: dict[str, Handler] = {}
        self._waiters: dict[str, asyncio.Future] = {}
        self._task: asyncio.Task | None = None
        self._pubsub = None
        self.ready = asyncio.Event()

    # ------------------------------------------------------------ 生命周期
    async def start(self) -> None:
        self._pubsub = self.redis.pubsub()
        await self._pubsub.subscribe(CHANNEL)
        self._task = asyncio.create_task(self._listen(), name="cluster-listener")
        self.ready.set()
        logger.info("集群桥已启动 role={} origin={}", self.role, self.origin)

    async def stop(self) -> None:
        if self._task:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._task
        if self._pubsub is not None:
            with contextlib.suppress(Exception):
                await self._pubsub.unsubscribe(CHANNEL)
                await self._pubsub.aclose()
        for fut in self._waiters.values():
            if not fut.done():
                fut.set_exception(ClusterUnavailable("集群桥已关闭"))

    def on_event(self, sink: Callable[[str, dict[str, Any]], Awaitable[None]]) -> None:
        self._event_sink = sink

    def on_hub(self, sink: Callable[[dict[str, Any]], Awaitable[None]]) -> None:
        self._hub_sink = sink

    def register(self, action: str, handler: Handler) -> None:
        self._rpc[action] = handler

    # ------------------------------------------------------------ 发送
    async def _send(self, message: dict[str, Any]) -> None:
        message["origin"] = self.origin
        await self.redis.publish(CHANNEL, json.dumps(message, ensure_ascii=False, default=str))

    async def broadcast_event(self, topic: str, payload: dict[str, Any]) -> None:
        await self._send({"kind": "event", "topic": topic, "payload": payload})

    async def broadcast_hub(self, message: dict[str, Any]) -> None:
        await self._send({"kind": "hub", "message": message})

    async def call(self, action: str, payload: dict[str, Any], timeout: float = 30.0) -> Any:
        """调用其他进程注册的处理器（由 Worker 执行），返回其结果或抛出异常。"""
        call_id = uuid.uuid4().hex
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._waiters[call_id] = fut
        try:
            await self._send({"kind": "call", "id": call_id, "action": action, "payload": payload})
            return await asyncio.wait_for(fut, timeout)
        except TimeoutError as e:
            raise ClusterUnavailable(f"{action} 无响应，请确认 Worker 进程在运行") from e
        finally:
            self._waiters.pop(call_id, None)

    # ------------------------------------------------------------ 分布式锁
    async def try_lock(self, key: str, ttl: int) -> str | None:
        token = uuid.uuid4().hex
        ok = await self.redis.set(f"xyh:lock:{key}", token, nx=True, ex=ttl)
        return token if ok else None

    async def unlock(self, key: str, token: str) -> None:
        script = "if redis.call('get', KEYS[1]) == ARGV[1] then return redis.call('del', KEYS[1]) end return 0"
        await self.redis.eval(script, 1, f"xyh:lock:{key}", token)

    # ------------------------------------------------------------ 接收
    async def _listen(self) -> None:
        assert self._pubsub is not None
        while True:
            try:
                msg = await self._pubsub.get_message(ignore_subscribe_messages=True, timeout=1.0)
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning("集群桥接收失败：{}，1s 后重试", e)
                await asyncio.sleep(1)
                continue
            if msg is None or msg.get("type") != "message":
                continue
            try:
                data = json.loads(msg["data"])
            except (TypeError, ValueError):
                continue
            if data.get("origin") == self.origin:
                continue
            asyncio.create_task(self._dispatch(data))

    async def _dispatch(self, data: dict[str, Any]) -> None:
        kind = data.get("kind")
        try:
            if kind == "event" and self._event_sink:
                await self._event_sink(data["topic"], data.get("payload") or {})
            elif kind == "hub" and self._hub_sink:
                await self._hub_sink(data.get("message") or {})
            elif kind == "call" and data.get("action") in self._rpc:
                try:
                    result = await self._rpc[data["action"]](data.get("payload") or {})
                    await self._send({"kind": "reply", "id": data["id"], "ok": True, "result": result})
                except Exception as e:  # noqa: BLE001
                    await self._send({"kind": "reply", "id": data["id"], "ok": False, "error": str(e)})
            elif kind == "reply":
                fut = self._waiters.get(data.get("id", ""))
                if fut is not None and not fut.done():
                    if data.get("ok"):
                        fut.set_result(data.get("result"))
                    else:
                        fut.set_exception(RuntimeError(data.get("error") or "远程调用失败"))
        except Exception:  # noqa: BLE001
            logger.exception("集群消息处理失败 kind={}", kind)


_cluster: Cluster | None = None


def get_cluster() -> Cluster | None:
    return _cluster


def set_cluster(cluster: Cluster | None) -> None:
    global _cluster
    _cluster = cluster
