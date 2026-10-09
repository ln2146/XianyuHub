import httpx
import respx

from app.core.db import session_factory
from app.domains.account.models import XyAccount
from app.domains.goods import service as goods_service


async def test_total_count_header_and_audit_pagination(admin_client):
    for i in range(3):
        await admin_client.post(
            "/api/v1/buyer/tasks",
            json={"name": f"t{i}", "keywords": ["k"], "cron": "*/30 8-23 * * *", "decision_mode": "rule"},
        )
    r = await admin_client.get("/api/v1/orders?limit=1")
    assert r.headers["x-total-count"] == "0"
    r = await admin_client.get("/api/v1/audit-logs?limit=1")
    assert r.status_code == 200 and int(r.headers["x-total-count"]) >= 0
    r = await admin_client.get("/api/v1/messages/conversations")
    assert r.headers["x-total-count"] == "0"
    r = await admin_client.get("/api/v1/buyer/results?verdict=all&limit=5")
    assert r.headers["x-total-count"] == "0"


async def test_grants_and_user_delete(admin_client):
    r = await admin_client.post("/api/v1/users", json={"username": "kefu", "password": "kefu-pass-1"})
    kefu_id = r.json()["id"]
    async with session_factory()() as s:
        s.add(XyAccount(owner_id=1, unb="9", device_id="d"))
        await s.commit()
    await admin_client.post("/api/v1/accounts/1/grants", json={"user_id": kefu_id})
    grants = (await admin_client.get("/api/v1/accounts/1/grants")).json()
    assert grants == [{"user_id": kefu_id, "username": "kefu", "role": "member"}]
    # 自己不能删；名下有账号的用户不能删
    assert (await admin_client.delete("/api/v1/users/1")).status_code == 400
    r = await admin_client.post("/api/v1/users", json={"username": "owner2", "password": "owner2-pass"})
    owner2 = r.json()["id"]
    async with session_factory()() as s:
        s.add(XyAccount(owner_id=owner2, unb="10", device_id="d"))
        await s.commit()
    r = await admin_client.delete(f"/api/v1/users/{owner2}")
    assert r.status_code == 409 and "闲鱼账号" in r.json()["detail"]
    assert (await admin_client.delete(f"/api/v1/users/{kefu_id}")).status_code == 204
    assert (await admin_client.get("/api/v1/accounts/1/grants")).json() == []


async def test_notify_meta_has_optional_fields(admin_client):
    meta = (await admin_client.get("/api/v1/notify/meta")).json()
    assert meta["optional"]["email"]["port"] == 465 and meta["types"]["telegram"] == ["bot_token", "chat_id"]


@respx.mock
async def test_market_view_is_cached(admin_client):
    goods_service._market_cache.clear()
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    search = respx.post(url__regex=r".*idlemtopsearch.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {"resultList": []}})
    )
    for _ in range(3):
        assert (await admin_client.get("/api/v1/goods/market?keyword=switch")).status_code == 200
    assert search.call_count == 1
