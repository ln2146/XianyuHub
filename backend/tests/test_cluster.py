import asyncio

import pytest
import respx
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from app.core.cluster import Cluster, ClusterUnavailable, set_cluster
from app.core.events import EventBus, bus
from app.core.realtime import RealtimeHub
from app.domains.message import service as message_service
from app.workers.im_gateway import ImGatewayManager, set_im_manager
from tests.test_accounts import COOKIES, mock_probe


@pytest.fixture
async def pair():
    server = FakeServer()
    api = Cluster(FakeRedis(server=server, decode_responses=True), "api")
    worker = Cluster(FakeRedis(server=server, decode_responses=True), "worker")
    await api.start()
    await worker.start()
    yield api, worker
    await api.stop()
    await worker.stop()


async def eventually(cond, timeout=3.0):
    for _ in range(int(timeout / 0.02)):
        if cond():
            return True
        await asyncio.sleep(0.02)
    return False


async def test_event_and_hub_bridging(pair):
    api, worker = pair
    api_bus, worker_bus = EventBus(), EventBus()
    api_bus.bridge, worker_bus.bridge = api, worker
    got_api, got_worker = [], []

    async def on_worker(p):
        got_worker.append(p)

    async def on_api(p):
        got_api.append(p)

    worker_bus.subscribe("t", on_worker)
    api_bus.subscribe("t", on_api)
    worker.on_event(lambda topic, p: worker_bus.publish(topic, p, remote=True))
    api.on_event(lambda topic, p: api_bus.publish(topic, p, remote=True))

    await api_bus.publish("t", {"n": 1})
    assert await eventually(lambda: got_worker == [{"n": 1}])
    assert got_api == [{"n": 1}]  # 本进程也分发一次，且不会被回环重复投递
    await asyncio.sleep(0.1)
    assert len(got_api) == 1 and len(got_worker) == 1

    hub_api = RealtimeHub()
    pushed = []

    async def on_hub(msg):
        pushed.append(msg)

    api.on_hub(on_hub)
    hub_worker = RealtimeHub()
    hub_worker.bridge = worker
    await hub_worker.publish("message", {"text": "hi"}, account_id=3)
    assert await eventually(lambda: pushed and pushed[0]["data"]["text"] == "hi")
    assert hub_api.size == 0


async def test_rpc_call_timeout_and_lock(pair):
    api, worker = pair

    async def echo(p):
        return {"double": p["n"] * 2}

    async def boom(p):
        raise ValueError("账号未连接")

    worker.register("echo", echo)
    worker.register("boom", boom)
    assert await api.call("echo", {"n": 21}) == {"double": 42}
    with pytest.raises(RuntimeError, match="账号未连接"):
        await api.call("boom", {})
    with pytest.raises(ClusterUnavailable):
        await api.call("missing", {}, timeout=0.3)

    token = await api.try_lock("task.1", 60)
    assert token and await worker.try_lock("task.1", 60) is None
    await api.unlock("task.1", token)
    assert await worker.try_lock("task.1", 60)


async def test_api_process_sends_through_worker(pair, admin_client):
    api, worker = pair
    sent = []

    async def rpc_send(p):
        sent.append(p)
        return True

    worker.register("im.send", rpc_send)
    set_cluster(api)
    try:
        with respx.mock:
            mock_probe()
            acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
        from app.core.db import session_factory
        from app.domains.message.models import Conversation

        async with session_factory()() as s:
            conv = Conversation(account_id=acc["id"], cid="c9", peer_id="3300")
            s.add(conv)
            await s.commit()
        r = await admin_client.post(f"/api/v1/messages/conversations/{conv.id}/send", json={"text": "在的"})
        assert r.status_code == 200, r.text
        assert sent == [{"account_id": acc["id"], "cid": "c9", "peer_id": "3300", "text": "在的"}]
    finally:
        set_cluster(None)


async def test_imported_account_starts_im_connection(admin_client):
    started = []

    class FakeIm:
        connected = asyncio.Event()

        async def run_forever(self):
            await asyncio.Event().wait()

        async def stop(self):
            pass

    async def factory(account_id, on_event, on_status):
        started.append(account_id)
        return FakeIm()

    manager = ImGatewayManager(message_service.handle_event, factory)
    set_im_manager(manager)
    bus.subscribe("account.status.changed", manager.on_account_status)
    try:
        with respx.mock:
            mock_probe()
            acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
            await bus.drain()
            assert started == [acc["id"]]
            # 重新登录：用新登录态重建连接
            mock_probe()
            await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})
            await bus.drain()
            assert started == [acc["id"], acc["id"]]
    finally:
        await manager.stop_all()
        set_im_manager(None)


async def test_redis_rate_limiter_lua():
    from app.goofish.guard.limiter import RedisRateLimiter

    lim = RedisRateLimiter(FakeRedis(server=FakeServer(), decode_responses=True))
    waits = [round(await lim.reserve("acc:1:search", 60, 60, 2), 1) for _ in range(4)]
    assert waits[:2] == [0.0, 0.0] and 0.9 <= waits[2] <= 1.0 and 1.9 <= waits[3] <= 2.0
