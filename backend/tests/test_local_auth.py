import httpx
import pytest

from app.core.config import get_settings

LOCAL = "http://127.0.0.1:8000"


async def local_client(app, client=("127.0.0.1", 50000), base_url=LOCAL) -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=app, client=client), base_url=base_url)


async def test_local_login_issues_admin_token(app):
    async with await local_client(app) as c:
        r = await c.post("/api/v1/auth/local", headers={"Origin": "http://localhost:5173"})
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["user"]["role"] == "admin"
        me = await c.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {body['access_token']}"})
        assert me.status_code == 200 and me.json()["username"] == "admin"
    # IPv6 回环 + localhost 也算本机
    async with await local_client(app, client=("::1", 50000), base_url="http://localhost:8000") as c:
        assert (await c.post("/api/v1/auth/local")).status_code == 200


@pytest.mark.parametrize(
    "client,base_url,headers,why",
    [
        (("192.168.1.20", 50000), LOCAL, {}, "局域网其他设备"),
        (("127.0.0.1", 50000), "http://evil.example.com", {}, "DNS 重绑定：Host 不是本机"),
        (("127.0.0.1", 50000), LOCAL, {"Origin": "https://evil.example.com"}, "其他网站跨站调用"),
        (("127.0.0.1", 50000), LOCAL, {"X-Forwarded-For": "203.0.113.9"}, "经反向代理转发"),
        (("127.0.0.1", 50000), LOCAL, {"Forwarded": "for=203.0.113.9"}, "经反向代理转发（标准头）"),
    ],
)
async def test_local_login_rejects_non_local_requests(app, client, base_url, headers, why):
    async with await local_client(app, client=client, base_url=base_url) as c:
        r = await c.post("/api/v1/auth/local", headers=headers)
        assert r.status_code == 404, why


async def test_local_login_can_be_disabled_and_is_off_in_production(app, monkeypatch):
    monkeypatch.setenv("LOCAL_AUTH", "false")
    get_settings.cache_clear()
    async with await local_client(app) as c:
        assert (await c.post("/api/v1/auth/local")).status_code == 404

    monkeypatch.setenv("LOCAL_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "production")
    get_settings.cache_clear()
    async with await local_client(app) as c:
        assert (await c.post("/api/v1/auth/local")).status_code == 404


async def test_other_endpoints_still_require_token(app):
    async with await local_client(app) as c:
        assert (await c.get("/api/v1/accounts")).status_code == 401
