import time
from types import SimpleNamespace

import httpx
import pytest
import respx
from fakeredis import FakeServer
from fakeredis.aioredis import FakeRedis

from app.core.config import get_settings
from app.domains.account import service
from app.goofish.guard import limiter as limiter_module
from app.goofish.guard.limiter import MemoryRateLimiter, RedisRateLimiter
from app.goofish.protocol.login import QrLoginClient


@pytest.mark.parametrize("redis", [False, True])
async def test_rejected_reservation_does_not_extend_wait(redis, monkeypatch):
    now = [1000.0]
    monkeypatch.setattr(limiter_module, "time", SimpleNamespace(time=lambda: now[0], monotonic=lambda: now[0]))
    redis_client = FakeRedis(server=FakeServer(), decode_responses=True) if redis else None
    limiter = RedisRateLimiter(redis_client) if redis else MemoryRateLimiter()
    try:
        assert await limiter.reserve("login", 2, 300, max_wait=0) == 0
        for _ in range(3):
            assert await limiter.reserve("login", 2, 300, max_wait=0) == pytest.approx(150)
        now[0] += 50
        assert await limiter.reserve("login", 2, 300, max_wait=0) == pytest.approx(100)
        now[0] += 100
        assert await limiter.reserve("login", 2, 300, max_wait=0) == 0
    finally:
        if redis_client is not None:
            await redis_client.aclose()


@respx.mock
async def test_qr_rate_limit_returns_wait_and_recovers(admin_client, monkeypatch):
    monkeypatch.setenv("GUARD_RATE_MULTIPLIER", "1")
    get_settings.cache_clear()
    manager = service.QrLoginManager()
    monkeypatch.setattr(service, "qr_manager", manager)
    clients = []

    def make_client(**kwargs):
        client = QrLoginClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr(service, "QrLoginClient", make_client)
    now = [time.monotonic()]
    monkeypatch.setattr(limiter_module, "time", SimpleNamespace(monotonic=lambda: now[0]))
    respx.get(url__regex=r".*mini_login\.htm.*").mock(
        return_value=httpx.Response(200, text="ok", headers={"set-cookie": "XSRF-TOKEN=csrf1; Path=/"})
    )
    generate = respx.get(url__regex=r".*qrcode/generate\.do.*").mock(
        return_value=httpx.Response(
            200, json={"content": {"data": {"codeContent": "https://qr/xyz", "t": 1, "ck": "ck1"}}}
        )
    )
    try:
        first = await admin_client.post("/api/v1/accounts/qr", json={})
        assert first.status_code == 200
        assert first.json()["qr_content"] == "https://qr/xyz"
        now[0] += 50  # 原逻辑此时会排队 100 秒，超过前端的 60 秒超时。
        for _ in range(3):
            blocked = await admin_client.post("/api/v1/accounts/qr", json={})
            assert blocked.status_code == 429
            assert blocked.headers["Retry-After"] == "100"
            assert "100 秒后重试" in blocked.json()["detail"]
            assert clients[-1]._http.is_closed
        assert generate.call_count == 1  # 被拒绝的请求不访问闲鱼。
        now[0] += 100
        recovered = await admin_client.post("/api/v1/accounts/qr", json={})
        assert recovered.status_code == 200
        assert generate.call_count == 2
    finally:
        for client in clients:
            await client.aclose()
