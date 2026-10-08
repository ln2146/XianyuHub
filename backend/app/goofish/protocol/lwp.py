"""闲鱼 IM 长连接客户端（钉钉 IMPaaS / LWP 协议）。

生命周期：取 accessToken → /reg → /r/SyncStatus/ackDiff → 心跳 /! → 每帧 ACK → 定期刷新 token 并重连。
一个账号一个 LwpClient；断线指数退避重连。
"""

import asyncio
import contextlib
import json
import random
import time
from collections.abc import Awaitable, Callable
from typing import Any

import websockets
from loguru import logger

from app.goofish.dto import ImEvent
from app.goofish.parsers.im import parse_message
from app.goofish.protocol.codec import decode_push_data, encode_custom
from app.goofish.protocol.sign import IM_APP_KEY, gen_mid, gen_uuid, now_ms

WSS_URL = "wss://wss-goofish.dingtalk.com/"
IM_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/140.0.0.0 Safari/537.36 DingTalk(2.1.5) OS(Mac/10.15.7) Browser(Chrome/140.0.0.0) "
    "DingWeb/2.1.5 IMPaaS DingWeb/2.1.5"
)

TokenProvider = Callable[[], Awaitable[str]]
EventHandler = Callable[[ImEvent], Awaitable[None]]
StatusHandler = Callable[[str, str | None], Awaitable[None]]


class LwpClient:
    def __init__(
        self,
        *,
        my_id: str,
        device_id: str,
        cookie_header: str,
        token_provider: TokenProvider,
        on_event: EventHandler,
        on_status: StatusHandler | None = None,
        heartbeat_interval: float = 15.0,
        heartbeat_timeout: float = 10.0,
        token_ttl: float = 55 * 60,
        connect: Callable[..., Any] | None = None,
        url: str = WSS_URL,
    ) -> None:
        self.my_id = my_id
        self.device_id = device_id
        self.cookie_header = cookie_header
        self._token_provider = token_provider
        self._on_event = on_event
        self._on_status = on_status
        self.heartbeat_interval = heartbeat_interval
        self.heartbeat_timeout = heartbeat_timeout
        self.token_ttl = token_ttl
        self._connect = connect or websockets.connect
        self.url = url
        self._ws: Any = None
        self._pending: dict[str, asyncio.Future] = {}
        self._last_pong = 0.0
        self._stop = asyncio.Event()
        self.connected = asyncio.Event()

    # ------------------------------------------------------------------ 公共 API
    async def run_forever(self) -> None:
        backoff = 1.0
        while not self._stop.is_set():
            try:
                await self._run_once()
                backoff = 1.0
            except asyncio.CancelledError:
                raise
            except Exception as e:  # noqa: BLE001
                logger.warning("IM 连接断开 uid={} err={!r}，{}s 后重连", self.my_id, e, int(backoff))
                await self._emit_status("disconnected", repr(e))
                if self._stop.is_set():
                    break
                with contextlib.suppress(TimeoutError):
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff + random.random())
                backoff = min(backoff * 2, 60.0)

    async def stop(self) -> None:
        self._stop.set()
        if self._ws is not None:
            with contextlib.suppress(Exception):
                await self._ws.close()

    async def send_text(self, cid: str, to_id: str, text: str) -> dict[str, Any]:
        return await self._send_custom(cid, to_id, 1, {"contentType": 1, "text": {"text": text}})

    async def send_image(self, cid: str, to_id: str, url: str, width: int, height: int) -> dict[str, Any]:
        payload = {"contentType": 2, "image": {"pics": [{"height": height, "type": 0, "url": url, "width": width}]}}
        return await self._send_custom(cid, to_id, 2, payload)

    async def create_conversation(self, to_id: str, item_id: str) -> str | None:
        body = [
            {
                "pairFirst": f"{to_id}@goofish",
                "pairSecond": f"{self.my_id}@goofish",
                "bizType": "1",
                "extension": {"itemId": item_id},
                "ctx": {"appVersion": "1.0", "platform": "web"},
            }
        ]
        resp = await self.request("/r/SingleChatConversation/create", body)
        cid = (resp.get("body") or {}).get("singleChatConversation", {}).get("cid")
        return cid.split("@", 1)[0] if cid else None

    async def request(self, lwp: str, body: Any, timeout: float = 10.0) -> dict[str, Any]:
        """发送请求帧，并等待相同 mid 的响应帧。"""
        if self._ws is None:
            raise ConnectionError("IM 未连接")
        mid = gen_mid()
        fut: asyncio.Future = asyncio.get_running_loop().create_future()
        self._pending[mid] = fut
        try:
            await self._ws.send(json.dumps({"lwp": lwp, "headers": {"mid": mid}, "body": body}, ensure_ascii=False))
            return await asyncio.wait_for(fut, timeout)
        finally:
            self._pending.pop(mid, None)

    # ------------------------------------------------------------------ 内部实现
    async def _emit_status(self, status: str, detail: str | None = None) -> None:
        if self._on_status:
            with contextlib.suppress(Exception):
                await self._on_status(status, detail)

    async def _send_custom(self, cid: str, to_id: str, custom_type: int, payload: dict[str, Any]) -> dict[str, Any]:
        body = [
            {
                "uuid": gen_uuid(),
                "cid": f"{cid}@goofish",
                "conversationType": 1,
                "content": {"contentType": 101, "custom": {"type": custom_type, "data": encode_custom(payload)}},
                "redPointPolicy": 0,
                "extension": {"extJson": "{}"},
                "ctx": {"appVersion": "1.0", "platform": "web"},
                "mtags": {},
                "msgReadStatusSetting": 1,
            },
            {"actualReceivers": [f"{to_id}@goofish", f"{self.my_id}@goofish"]},
        ]
        resp = await self.request("/r/MessageSend/sendByReceiverScope", body)
        code = resp.get("code")
        if code not in (None, 200):
            raise RuntimeError(f"发送失败 code={code} body={resp.get('body')}")
        return resp

    async def _register(self, ws: Any, token: str) -> None:
        await ws.send(
            json.dumps(
                {
                    "lwp": "/reg",
                    "headers": {
                        "cache-header": "app-key token ua wv",
                        "app-key": IM_APP_KEY,
                        "token": token,
                        "ua": IM_UA,
                        "dt": "j",
                        "wv": "im:3,au:3,sy:6",
                        "sync": "0,0;0;0;",
                        "did": self.device_id,
                        "mid": gen_mid(),
                    },
                }
            )
        )
        await asyncio.sleep(0.5)
        ts = now_ms()
        await ws.send(
            json.dumps(
                {
                    "lwp": "/r/SyncStatus/ackDiff",
                    "headers": {"mid": gen_mid()},
                    "body": [
                        {
                            "pipeline": "sync",
                            "tooLong2Tag": "PNM,1",
                            "channel": "sync",
                            "topic": "sync",
                            "highPts": 0,
                            "pts": ts * 1000,
                            "seq": 0,
                            "timestamp": ts,
                        }
                    ],
                }
            )
        )

    async def _run_once(self) -> None:
        token = await self._token_provider()
        headers = {
            "Cookie": self.cookie_header,
            "Origin": "https://www.goofish.com",
            "User-Agent": IM_UA.split(" DingTalk", 1)[0],
            "Accept-Language": "zh-CN,zh;q=0.9",
        }
        async with self._connect(self.url, additional_headers=headers, max_size=8 * 1024 * 1024) as ws:
            self._ws = ws
            await self._register(ws, token)
            self._last_pong = time.monotonic()
            self.connected.set()
            await self._emit_status("connected")
            started = time.monotonic()
            hb = asyncio.create_task(self._heartbeat_loop(ws))
            try:
                async for raw in ws:
                    await self._on_frame(ws, raw)
                    if time.monotonic() - started > self.token_ttl:
                        logger.info("IM token 到期，主动重连 uid={}", self.my_id)
                        break
            finally:
                hb.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await hb
                self.connected.clear()
                self._ws = None
                for fut in self._pending.values():
                    if not fut.done():
                        fut.set_exception(ConnectionError("IM 连接已断开"))

    async def _heartbeat_loop(self, ws: Any) -> None:
        while True:
            await asyncio.sleep(self.heartbeat_interval)
            await ws.send(json.dumps({"lwp": "/!", "headers": {"mid": gen_mid()}}))
            if time.monotonic() - self._last_pong > self.heartbeat_interval + self.heartbeat_timeout:
                logger.warning("IM 心跳超时 uid={}", self.my_id)
                await ws.close()
                return

    async def _on_frame(self, ws: Any, raw: str | bytes) -> None:
        try:
            frame = json.loads(raw)
        except (TypeError, ValueError):
            return
        headers = frame.get("headers") or {}
        self._last_pong = time.monotonic()

        mid = headers.get("mid")
        if mid and mid in self._pending and "code" in frame:
            fut = self._pending.pop(mid)
            if not fut.done():
                fut.set_result(frame)
            return

        # 服务端推送需要 ACK
        if mid and "lwp" in frame:
            ack = {"code": 200, "headers": {"mid": mid, "sid": headers.get("sid", "")}}
            for key in ("app-key", "ua", "dt"):
                if key in headers:
                    ack["headers"][key] = headers[key]
            await ws.send(json.dumps(ack))

        package = (frame.get("body") or {}).get("syncPushPackage") if isinstance(frame.get("body"), dict) else None
        if not package:
            return
        for entry in package.get("data") or []:
            data = entry.get("data") if isinstance(entry, dict) else None
            if not data:
                continue
            kind, obj = decode_push_data(data)
            if kind != "msgpack":
                continue
            event = parse_message(obj)
            try:
                await self._on_event(event)
            except Exception:  # noqa: BLE001
                logger.exception("IM 事件处理失败 uid={}", self.my_id)
