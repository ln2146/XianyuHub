"""浏览器扩展自动续期：专用令牌只能同步登录态；只在账号掉线时用浏览器里的登录态恢复。"""

import respx

from app.core.db import session_factory
from app.domains.account.models import XyAccount
from app.domains.account.store import DbSessionStore
from app.goofish.guard.guard import AccountState
from tests.test_accounts import COOKIES, mock_probe

NEW_COOKIES = "unb=2200888; cookie2=new_c2; _m_h5_tk=tk_2; tracknick=小鱼"


async def _sync_token(admin_client) -> dict:
    r = await admin_client.post("/api/v1/accounts/cookie-sync/token")
    assert r.status_code == 200 and r.json()["expires_in_days"] == 180
    return {"Authorization": f"Bearer {r.json()['token']}"}


async def test_sync_token_cannot_be_used_as_a_login_token(admin_client):
    h = await _sync_token(admin_client)
    assert (await admin_client.get("/api/v1/auth/me", headers=h)).status_code == 401
    assert (await admin_client.get("/api/v1/accounts", headers=h)).status_code == 401
    # 反过来，普通登录令牌也不能调同步接口
    r = await admin_client.post("/api/v1/accounts/cookie-sync", json={"cookies": COOKIES})
    assert r.status_code == 401


@respx.mock
async def test_sync_only_renews_an_account_that_needs_login(admin_client):
    mock_probe()
    acc = (await admin_client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()
    h = await _sync_token(admin_client)

    # 账号正常：不动它
    r = await admin_client.post("/api/v1/accounts/cookie-sync", json={"cookies": NEW_COOKIES}, headers=h)
    assert r.json() == {"result": "healthy", "account_id": acc["id"]}
    assert (await DbSessionStore().load_cookies(acc["id"]))["cookie2"] == "c2val"

    # 掉线后：用浏览器里的登录态恢复
    async with session_factory()() as s:
        (await s.get(XyAccount, acc["id"])).status = AccountState.NEED_LOGIN
        await s.commit()
    r = await admin_client.post("/api/v1/accounts/cookie-sync", json={"cookies": NEW_COOKIES}, headers=h)
    assert r.json() == {"result": "renewed", "account_id": acc["id"]}
    assert (await DbSessionStore().load_cookies(acc["id"]))["cookie2"] == "new_c2"
    async with session_factory()() as s:
        assert (await s.get(XyAccount, acc["id"])).status == AccountState.ACTIVE

    # 浏览器退出了闲鱼 / 登录的是没添加过的号：什么都不做
    r = await admin_client.post("/api/v1/accounts/cookie-sync", json={"cookies": "unb=1; cookie2=x"}, headers=h)
    assert r.json()["result"] == "browser_logged_out"
    other = "unb=9999; cookie2=x; _m_h5_tk=y"
    r = await admin_client.post("/api/v1/accounts/cookie-sync", json={"cookies": other}, headers=h)
    assert r.json()["result"] == "not_found"
