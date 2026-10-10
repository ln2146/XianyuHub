import json

import httpx
import pytest
import respx

from app.notify.senders import Notification
from app.notify.service import NotifyEvents, notify


@respx.mock
async def test_channel_crud_mask_and_test(admin_client):
    route = respx.post("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRETKEY123").mock(
        return_value=httpx.Response(200, json={"errcode": 0})
    )
    r = await admin_client.post(
        "/api/v1/notify/channels",
        json={
            "name": "企微",
            "type": "wecom",
            "config": {"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=SECRETKEY123"},
            "events": [NotifyEvents.ITEM_RECOMMENDED],
        },
    )
    assert r.status_code == 201, r.text
    ch = r.json()
    assert "SECRETKEY123" not in json.dumps(ch)

    # 回传打码值不会覆盖原配置
    r = await admin_client.patch(f"/api/v1/notify/channels/{ch['id']}", json={"config": ch["config"], "name": "企微2"})
    assert r.status_code == 200 and r.json()["name"] == "企微2"

    r = await admin_client.post(f"/api/v1/notify/channels/{ch['id']}/test")
    assert r.json() == {"ok": True, "error": None}
    assert route.called

    sent = await notify(None, Notification(event=NotifyEvents.ITEM_RECOMMENDED, title="好货", content="M1 Air 3200"))
    assert sent == 1
    assert await notify(None, Notification(event=NotifyEvents.ORDER_PAID, title="x", content="y")) == 0


async def test_channel_validation(admin_client):
    r = await admin_client.post("/api/v1/notify/channels", json={"name": "x", "type": "telegram", "config": {}})
    assert r.status_code == 400 and "bot_token" in r.json()["detail"]


@respx.mock
async def test_probe_unsaved_channel(admin_client):
    respx.post("https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=PROBE123").mock(
        return_value=httpx.Response(200, json={"errcode": 0})
    )
    r = await admin_client.post(
        "/api/v1/notify/test",
        json={
            "type": "wecom",
            "name": "测试未保存连接器",
            "config": {"webhook_url": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=PROBE123"},
        },
    )
    assert r.status_code == 200
    assert r.json()["ok"] is True


@respx.mock
async def test_webhook_failure_recorded(admin_client):
    respx.post("https://hook.example.com/x").mock(return_value=httpx.Response(500, text="boom"))
    r = await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "hook", "type": "webhook", "config": {"url": "https://hook.example.com/x"}},
    )
    r = await admin_client.post(f"/api/v1/notify/channels/{r.json()['id']}/test")
    assert r.json()["ok"] is False and "500" in r.json()["error"]


@respx.mock
async def test_wechat_personal_senders():
    from app.notify.senders import Notification as N
    from app.notify.senders import SendError, send_pushplus, send_serverchan

    n = N(
        event="item_recommended",
        title="✅ 推荐｜iPhone 13",
        content="¥1999 杭州",
        url="https://www.goofish.com/item?id=1",
    )
    turbo = respx.post("https://sctapi.ftqq.com/SCT123abc.send").mock(
        return_value=httpx.Response(200, json={"code": 0})
    )
    sc3 = respx.post("https://8848.push.ft07.com/send/sctp8848tXYZ.send").mock(
        return_value=httpx.Response(200, json={"code": 0})
    )
    plus = respx.post("https://www.pushplus.plus/send").mock(return_value=httpx.Response(200, json={"code": 200}))
    async with httpx.AsyncClient() as http:
        await send_serverchan(http, {"sendkey": "SCT123abc"}, n)
        await send_serverchan(http, {"sendkey": " sctp8848tXYZ "}, n)
        await send_pushplus(http, {"token": "tok"}, n)
        body = json.loads(plus.calls[0].request.content)
        assert body["template"] == "markdown" and "查看详情" in body["content"] and body["token"] == "tok"
        assert json.loads(turbo.calls[0].request.content)["title"].startswith("✅ 推荐") and sc3.called

        respx.post("https://sctapi.ftqq.com/BAD.send").mock(return_value=httpx.Response(200, json={"code": 40001}))
        with pytest.raises(SendError):
            await send_serverchan(http, {"sendkey": "BAD"}, n)
        plus.mock(return_value=httpx.Response(200, json={"code": 903, "msg": "无效的用户token"}))
        with pytest.raises(SendError):
            await send_pushplus(http, {"token": "bad"}, n)


@respx.mock
async def test_signed_bots_and_ntfy_json():
    import base64
    import hashlib
    import hmac
    import urllib.parse

    from app.notify.senders import dingtalk_signed_url, feishu_sign, send_dingtalk, send_feishu, send_ntfy

    # 签名算法与官方文档示例一致
    digest = hmac.new(b"SECxx", b"1700000000000\nSECxx", hashlib.sha256).digest()
    expected = urllib.parse.quote_plus(base64.b64encode(digest).decode())
    assert dingtalk_signed_url("https://oapi.dingtalk.com/robot/send?access_token=t", "SECxx", 1700000000000) == (
        f"https://oapi.dingtalk.com/robot/send?access_token=t&timestamp=1700000000000&sign={expected}"
    )
    key = b"1700000000\nfs"
    assert feishu_sign("fs", 1700000000) == base64.b64encode(hmac.new(key, b"", hashlib.sha256).digest()).decode()

    n = Notification(event="x", title="中文标题", content="正文", url="https://u")
    ding = respx.post(url__startswith="https://oapi.dingtalk.com/robot/send").mock(
        return_value=httpx.Response(200, json={"errcode": 0})
    )
    fei = respx.post("https://open.feishu.cn/hook/x").mock(return_value=httpx.Response(200, json={"code": 0}))
    ntfy = respx.post("https://ntfy.sh").mock(return_value=httpx.Response(200))
    async with httpx.AsyncClient() as http:
        await send_dingtalk(
            http, {"webhook_url": "https://oapi.dingtalk.com/robot/send?access_token=t", "secret": "S"}, n
        )
        await send_feishu(http, {"webhook_url": "https://open.feishu.cn/hook/x", "secret": "S"}, n)
        await send_ntfy(http, {"topic": "fish"}, n)
    assert "sign=" in str(ding.calls[0].request.url)
    assert {"timestamp", "sign"} <= set(json.loads(fei.calls[0].request.content))
    body = json.loads(ntfy.calls[0].request.content)
    assert body == {"topic": "fish", "title": "中文标题", "message": "正文", "tags": ["fish"], "click": "https://u"}


@respx.mock
async def test_retry_dedupe_and_mask(admin_client, monkeypatch):
    from app.notify import service as notify_service

    monkeypatch.setattr(notify_service, "RETRY_DELAY_SECONDS", 0)
    route = respx.post("https://hook.example.com/r").mock(
        side_effect=[httpx.Response(502), httpx.Response(200), httpx.Response(200)]
    )
    await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "h", "type": "webhook", "config": {"url": "https://hook.example.com/r"}},
    )
    n = Notification(event=NotifyEvents.ACCOUNT_RISK, title="风控", content="x")
    # 第一次 502 后自动重试成功
    assert await notify(None, n, dedupe_key="k") == 1 and route.call_count == 2
    # 冷却期内同一 key 不再发送
    assert await notify(None, n, dedupe_key="k") == 0 and route.call_count == 2
    # 4xx 是配置问题，不重试
    route.side_effect = [httpx.Response(404)]
    assert await notify(None, n) == 0 and route.call_count == 3

    r = await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "sc", "type": "serverchan", "config": {"sendkey": "SCT1234567890abcdef"}},
    )
    assert "SCT1234567890abcdef" not in json.dumps(r.json())


async def test_ownerless_events_only_reach_admins(admin_client):
    from app.core.db import session_factory
    from app.core.security import hash_password
    from app.domains.system.models import Role, User
    from app.notify.models import NotificationChannel
    from app.notify.service import encode_config

    async with session_factory()() as s:
        member = User(username="m", password_hash=hash_password("x" * 12), role=Role.MEMBER)
        s.add(member)
        await s.flush()
        s.add(
            NotificationChannel(
                owner_id=member.id, name="m", type="webhook", config_enc=encode_config({"url": "https://m"}), events=[]
            )
        )
        await s.commit()
    # 只有普通成员有渠道时，无归属事件不会发给他
    assert await notify(None, Notification(event=NotifyEvents.ACCOUNT_RISK, title="t", content="c")) == 0
