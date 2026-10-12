import asyncio
import base64
import contextlib
import json

import msgpack

from app.goofish.dto import ImEvent
from app.goofish.protocol.lwp import LwpClient


class FakeWS:
    """模拟 IM 服务端：记录客户端发出的帧，并按需推送 / 应答。"""

    def __init__(self):
        self.sent: list[dict] = []
        self.inbox: asyncio.Queue = asyncio.Queue()
        self.closed = False

    async def send(self, raw):
        frame = json.loads(raw)
        self.sent.append(frame)
        lwp = frame.get("lwp")
        if lwp in ("/r/MessageSend/sendByReceiverScope", "/r/SingleChatConversation/create"):
            body = {"singleChatConversation": {"cid": "777@goofish"}} if "Conversation" in lwp else {}
            await self.inbox.put(json.dumps({"code": 200, "headers": {"mid": frame["headers"]["mid"]}, "body": body}))

    async def close(self):
        self.closed = True
        await self.inbox.put(None)

    def __aiter__(self):
        return self

    async def __anext__(self):
        item = await self.inbox.get()
        if item is None:
            raise StopAsyncIteration
        return item


def make_connect(ws: FakeWS):
    @contextlib.asynccontextmanager
    async def _connect(url, **kwargs):
        yield ws

    return _connect


async def test_lwp_register_ack_dispatch_and_send():
    ws = FakeWS()
    events: list[ImEvent] = []

    async def on_event(ev):
        events.append(ev)

    async def token():
        return "ACCESS"

    client = LwpClient(
        my_id="1000",
        device_id="DEV-1000",
        cookie_header="unb=1000",
        token_provider=token,
        on_event=on_event,
        heartbeat_interval=100,
        connect=make_connect(ws),
    )
    task = asyncio.create_task(client.run_forever())
    await asyncio.wait_for(client.connected.wait(), 2)

    reg = ws.sent[0]
    assert reg["lwp"] == "/reg" and reg["headers"]["token"] == "ACCESS" and reg["headers"]["did"] == "DEV-1000"
    assert ws.sent[1]["lwp"] == "/r/SyncStatus/ackDiff"

    push_msg = {1: {2: "50001@goofish", 5: 1759900000000, 10: {"reminderContent": "在吗", "senderUserId": "3300"}}}
    data = base64.b64encode(msgpack.packb(push_msg)).decode()
    await ws.inbox.put(
        json.dumps(
            {
                "lwp": "/s/sync",
                "headers": {"mid": "m-1", "sid": "s-1"},
                "body": {"syncPushPackage": {"data": [{"data": data}]}},
            }
        )
    )
    for _ in range(50):
        if events:
            break
        await asyncio.sleep(0.01)
    assert events and events[0].text == "在吗" and events[0].cid == "50001"
    assert any(f.get("code") == 200 and f["headers"]["mid"] == "m-1" for f in ws.sent)

    await client.send_text("50001", "3300", "在的")
    sent = [f for f in ws.sent if f.get("lwp") == "/r/MessageSend/sendByReceiverScope"][-1]
    custom = sent["body"][0]["content"]["custom"]
    assert json.loads(base64.b64decode(custom["data"]))["text"]["text"] == "在的"
    assert sent["body"][1]["actualReceivers"] == ["3300@goofish", "1000@goofish"]

    assert await client.create_conversation("3300", "900") == "777"

    await client.stop()
    await asyncio.wait_for(task, 2)


async def test_lwp_backs_off_when_server_keeps_closing_and_refreshes_cookie(monkeypatch):
    # 服务端一连上就正常关闭（如鉴权被拒）：不能立即无限重连；每次重连都要取最新 Cookie
    import app.goofish.protocol.lwp as lwp

    monkeypatch.setattr(lwp.random, "random", lambda: 0.0)

    async def no_register(self, ws, token):
        pass

    monkeypatch.setattr(LwpClient, "_register", no_register)
    connects: list[str] = []
    statuses: list[tuple[str, str | None]] = []
    cookies = iter(f"unb=1000; v={i}" for i in range(1000))

    @contextlib.asynccontextmanager
    async def connect(url, additional_headers, **kwargs):
        connects.append(additional_headers["Cookie"])
        ws = FakeWS()
        await ws.inbox.put(None)  # 立刻结束迭代 = 服务端正常关闭
        yield ws

    async def token():
        return "ACCESS"

    async def cookie():
        return next(cookies)

    async def on_status(status, detail):
        statuses.append((status, detail))

    async def on_event(_):
        pass

    client = LwpClient(
        my_id="1000",
        device_id="DEV-1000",
        cookie_header=cookie,
        token_provider=token,
        on_event=on_event,
        on_status=on_status,
        heartbeat_interval=100,
        min_backoff=0.01,
        max_backoff=0.08,
        connect=connect,
    )
    task = asyncio.create_task(client.run_forever())
    await asyncio.sleep(0.3)
    await client.stop()
    await asyncio.wait_for(task, 2)
    # 退避 0.01 → 0.02 → 0.04 → 0.08 …：0.3 秒内只会重连几次（修复前会连上成千上万次）
    assert 3 <= len(connects) <= 10
    assert connects[0] != connects[1]  # 每次重连都是新取的 Cookie
    assert ("disconnected", "服务端关闭了连接") in statuses
