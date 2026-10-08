import pytest
from cryptography.exceptions import InvalidTag

from app.core.crypto import Vault, get_vault
from app.core.events import EventBus


def test_vault_roundtrip():
    vault = get_vault()
    token = vault.encrypt("cookie2=secret; unb=123")
    assert token and "secret" not in token
    assert vault.decrypt(token) == "cookie2=secret; unb=123"
    assert vault.encrypt(None) is None


def test_vault_rejects_wrong_key():
    a = Vault(b"a" * 32)
    b = Vault(b"b" * 32)
    with pytest.raises(InvalidTag):
        b.decrypt(a.encrypt("x"))


async def test_event_bus_dispatch():
    bus = EventBus()
    got = []

    async def handler(payload):
        got.append(payload["n"])

    async def broken(payload):
        raise RuntimeError("boom")

    bus.subscribe("t", handler)
    bus.subscribe("t", broken)
    await bus.publish("t", {"n": 1})
    await bus.drain()
    assert got == [1]


async def test_api_requires_auth(client):
    assert (await client.get("/api/v1/auth/me")).status_code == 401
    assert (await client.get("/api/v1/users")).status_code == 401


async def test_login_and_me(admin_client):
    resp = await admin_client.get("/api/v1/auth/me")
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"


async def test_login_lockout(client):
    for _ in range(5):
        r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": "wrong-pass"})
        assert r.status_code == 401
    from tests.conftest import ADMIN_PASSWORD

    r = await client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert r.status_code == 401
    assert "锁定" in r.json()["detail"]


async def test_user_management_and_rbac(admin_client, client):
    r = await admin_client.post(
        "/api/v1/users", json={"username": "kefu", "password": "kefu-pass-1", "role": "member"}
    )
    assert r.status_code == 201
    users = (await admin_client.get("/api/v1/users")).json()
    assert {u["username"] for u in users} == {"admin", "kefu"}

    login = await client.post("/api/v1/auth/login", json={"username": "kefu", "password": "kefu-pass-1"})
    token = login.json()["access_token"]
    r = await client.get("/api/v1/users", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 403
