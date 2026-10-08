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
