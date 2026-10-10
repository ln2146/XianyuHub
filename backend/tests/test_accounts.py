import asyncio

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_factory
from app.domains.account.models import RiskEvent, XyAccount
from app.domains.account.store import DbSessionStore
from app.goofish.gateway import account_key
from app.goofish.guard.guard import AccountState
from app.runtime import get_runtime

COOKIES = "unb=2200888; cookie2=c2val; _m_h5_tk=tk_1; tracknick=小鱼"


def mock_probe(ok: bool = True):
    ret = ["SUCCESS::调用成功"] if ok else ["FAIL_SYS_SESSION_EXPIRED::Session过期"]
    return respx.post(url__regex=r".*mtop\.taobao\.idlemessage\.pc\.loginuser\.get.*").mock(
        return_value=httpx.Response(200, json={"ret": ret, "data": {"nick": "小鱼塘主"}})
    )


@respx.mock
async def test_import_account_encrypts_cookie(admin_client):
    mock_probe()
    r = await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES, "proxy": "http://p:1"})
    assert r.status_code == 201, r.text
    acc = r.json()
    assert acc["unb"] == "2200888" and acc["nickname"] == "小鱼塘主" and acc["status"] == "active"
    assert acc["has_proxy"] and "proxy" not in acc
    assert acc["settings"]["auto_reply"] is False  # 自动化默认关闭

    cookies = await DbSessionStore().load_cookies(acc["id"])
    assert cookies["cookie2"] == "c2val"
    async with session_factory()() as s:
        from app.domains.account.models import XyAccountCredential

        cred = (await s.execute(select(XyAccountCredential))).scalar_one()
        assert "c2val" not in cred.cookie_enc

    r = await admin_client.patch(
        f"/api/v1/accounts/{acc['id']}", json={"settings": {"auto_reply": True, "ai_mode": "auto"}}
    )
    assert r.json()["settings"]["auto_reply"] is True and r.json()["settings"]["takeover_minutes"] == 60


@respx.mock
async def test_import_rejects_incomplete_or_expired(admin_client):
    r = await admin_client.post("/api/v1/accounts/import", json={"cookies": "unb=1"})
    assert r.status_code == 400
    mock_probe(ok=False)
    respx.post(url__regex=r".*hasLogin\.do.*").mock(
        return_value=httpx.Response(200, json={"content": {"success": False}})
    )
    r = await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})
    assert r.status_code == 400
    assert get_runtime().guard.runtime(account_key(1)).state == AccountState.NEED_LOGIN


@respx.mock
async def test_risk_trip_persists_and_resolves(admin_client):
    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    respx.post(url__regex=r".*merchant\.sold\.get.*").mock(
        return_value=httpx.Response(
            200,
            json={"ret": ["FAIL_SYS_USER_VALIDATE"], "data": {"url": "https://h5api.m.goofish.com/punish?x5secdata=1"}},
        )
    )
    import pytest

    from app.goofish.errors import RiskControlError

    with pytest.raises(RiskControlError):
        await get_runtime().gateway.list_sold_orders(acc["id"])
    from app.core.events import bus

    await bus.drain()

    r = await admin_client.get(f"/api/v1/accounts/{acc['id']}")
    assert r.json()["status"] == "circuit_open" and "punish" in r.json()["punish_url"]
    async with session_factory()() as s:
        db_acc = await s.get(XyAccount, acc["id"])
        assert db_acc.status == "circuit_open"
        assert (await s.execute(select(RiskEvent))).scalar_one().state == "circuit_open"
    events = (await admin_client.get(f"/api/v1/accounts/{acc['id']}/risk-events")).json()
    assert len(events) == 1

    r = await admin_client.post(f"/api/v1/accounts/{acc['id']}/resolve")
    assert r.json()["status"] == "cooldown"


async def test_member_cannot_see_others_accounts(admin_client, client):
    async with session_factory()() as s:
        s.add(XyAccount(owner_id=1, unb="1", device_id="d"))
        await s.commit()
    await admin_client.post("/api/v1/users", json={"username": "kefu", "password": "kefu-pass-1"})
    token = (await client.post("/api/v1/auth/login", json={"username": "kefu", "password": "kefu-pass-1"})).json()[
        "access_token"
    ]
    h = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/accounts", headers=h)).json() == []
    assert (await client.get("/api/v1/accounts/1", headers=h)).status_code == 404
    await admin_client.post("/api/v1/accounts/1/grants", json={"user_id": 2}, headers={})


@respx.mock
async def test_qr_login_flow(admin_client):
    respx.get(url__regex=r".*mini_login\.htm.*").mock(
        return_value=httpx.Response(200, text="ok", headers={"set-cookie": "XSRF-TOKEN=csrf1; Path=/"})
    )
    respx.get(url__regex=r".*qrcode/generate\.do.*").mock(
        return_value=httpx.Response(
            200, json={"content": {"data": {"codeContent": "https://qr/xyz", "t": 1, "ck": "ck1"}}}
        )
    )
    statuses = iter(["NEW", "CONFIRMED"])

    def query(request):
        st = next(statuses)
        headers = (
            [("set-cookie", "unb=2200999; Path=/"), ("set-cookie", "cookie2=c9; Path=/")] if st == "CONFIRMED" else []
        )
        return httpx.Response(200, json={"content": {"data": {"qrCodeStatus": st}}}, headers=headers)

    respx.post(url__regex=r".*qrcode/query\.do.*").mock(side_effect=query)
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(
            200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=new_1"}
        )
    )
    r = await admin_client.post("/api/v1/accounts/qr", json={})
    assert r.status_code == 200 and r.json()["qr_content"] == "https://qr/xyz"
    qr_id = r.json()["qr_id"]
    assert (await admin_client.get(f"/api/v1/accounts/qr/{qr_id}")).json()["status"] == "NEW"
    r = (await admin_client.get(f"/api/v1/accounts/qr/{qr_id}")).json()
    assert r["status"] == "SUCCESS" and r["account_id"]
    cookies = await DbSessionStore().load_cookies(r["account_id"])
    assert cookies["unb"] == "2200999" and cookies["_m_h5_tk"] == "new_1"
    assert r["relogin"] is False  # 新增的账号

    # 给已有账号重新登录：同一个号 → 标明是重新登录；扫了别的号 → 拒绝，不新增也不覆盖
    mock_probe()
    mine = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()  # unb 2200888
    for target, expect_status in ((r["account_id"], "SUCCESS"), (mine["id"], "ERROR")):
        statuses = iter(["CONFIRMED"])
        qr = (await admin_client.post("/api/v1/accounts/qr", json={"account_id": target})).json()
        res = (await admin_client.get(f"/api/v1/accounts/qr/{qr['qr_id']}")).json()
        assert res["status"] == expect_status
        if expect_status == "SUCCESS":
            assert res["relogin"] is True and res["account_id"] == target
        else:
            assert "另一个闲鱼账号" in res["message"]
    assert len((await admin_client.get("/api/v1/accounts")).json()) == 2


@respx.mock
async def test_account_relogin_clears_error(admin_client: httpx.AsyncClient):
    mock_probe(True)
    acc = (
        await admin_client.post(
            "/api/v1/accounts/import",
            json={"cookies": COOKIES, "proxy": "http://127.0.0.1:8888"},
        )
    ).json()
    account_id = acc["id"]

    # 模拟发生过期错误
    from app.goofish.gateway import account_key
    from app.runtime import get_runtime

    guard_rt = get_runtime().guard.runtime(account_key(account_id))
    guard_rt.last_error = "FAIL_SYS_SESSION_EXPIRED::Session expired"

    # 验证此时读取账号带错误
    r = await admin_client.get(f"/api/v1/accounts/{account_id}")
    assert "SESSION_EXPIRED" in r.json()["last_error"]

    # 重新登录（导入新 Cookie，继承原代理）
    new_cookies = COOKIES.replace("unb=2219896089989", "unb=2219896089989") + "; cookie2=updated_cookie"
    r2 = await admin_client.post(
        "/api/v1/accounts/import",
        json={"cookies": new_cookies, "account_id": account_id, "verify": False},
    )
    assert r2.status_code == 201
    updated_acc = r2.json()
    assert updated_acc["id"] == account_id
    assert updated_acc["status"] == "active"
    assert updated_acc["last_error"] is None
    assert updated_acc["has_proxy"] is True


@respx.mock
async def test_relogin_with_another_accounts_cookie_is_refused(admin_client):
    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    other = "unb=2200999; cookie2=x; _m_h5_tk=tk_2; tracknick=别人"
    r = await admin_client.post("/api/v1/accounts/import", json={"cookies": other, "account_id": acc["id"]})
    assert r.status_code == 409 and "另一个闲鱼账号" in r.json()["detail"]
    assert len((await admin_client.get("/api/v1/accounts")).json()) == 1  # 没有悄悄新增账号


async def test_delete_account_stops_im_and_removes_its_rules_and_bindings(admin_client):
    from app.core.events import Topics, bus

    with respx.mock:
        mock_probe()
        acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    rule = {"name": "r", "account_id": acc["id"], "keywords": ["在吗"], "reply": "在"}
    assert (await admin_client.post("/api/v1/messages/rules", json=rule)).status_code == 201
    shared = {**rule, "account_id": None, "name": "全部账号"}
    assert (await admin_client.post("/api/v1/messages/rules", json=shared)).status_code == 201
    pool = (await admin_client.post("/api/v1/cards/pools", json={"name": "p", "kind": "pool"})).json()
    binding = {"pool_id": pool["id"], "account_id": acc["id"], "item_id": "1"}
    assert (await admin_client.post("/api/v1/cards/bindings", json=binding)).status_code == 201

    events: list[dict] = []

    async def record(payload):
        events.append(payload)

    bus.subscribe(Topics.ACCOUNT_STATUS_CHANGED, record)
    try:
        assert (await admin_client.delete(f"/api/v1/accounts/{acc['id']}")).status_code == 204
        await asyncio.sleep(0.05)  # 事件总线异步分发
    finally:
        bus._handlers[Topics.ACCOUNT_STATUS_CHANGED].remove(record)
    # IM 管理器收到「停用」就会断开连接（否则删除后仍在线收消息、不停重连）
    assert {"account_id": acc["id"], "state": AccountState.DISABLED}.items() <= events[-1].items()
    rules = (await admin_client.get("/api/v1/messages/rules")).json()
    assert [r["name"] for r in rules] == ["全部账号"]  # 只删这个账号专属的
    assert (await admin_client.get("/api/v1/cards/bindings")).json() == []


@respx.mock
async def test_relogin_auto_resolves_past_risk_events(admin_client):
    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    # 模拟发生登录失效，记录了一条未解除的 RiskEvent
    async with session_factory()() as s:
        s.add(RiskEvent(account_id=acc["id"], guard_key=f"acc:{acc['id']}", state="need_login", reason="登录态失效"))
        await s.commit()

    # 查 risk-events：此时 resolved_at 仍是 None
    events = (await admin_client.get(f"/api/v1/accounts/{acc['id']}/risk-events")).json()
    assert len(events) == 1 and events[0]["resolved_at"] is None

    # 用户重新导入 Cookie / 重新扫码登录
    await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES, "account_id": acc["id"]})

    # 验证：重新登录成功后，历史未解决事件已自动标记解除
    events = (await admin_client.get(f"/api/v1/accounts/{acc['id']}/risk-events")).json()
    assert len(events) == 1 and events[0]["resolved_at"] is not None

    # 验证：系统总览接口中也同步显示 resolved 为 True
    dash = (await admin_client.get("/api/v1/dashboard")).json()
    assert all(r["resolved"] for r in dash["risk_events"])
