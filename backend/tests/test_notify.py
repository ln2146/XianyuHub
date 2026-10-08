import json

import httpx
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
async def test_webhook_failure_recorded(admin_client):
    respx.post("https://hook.example.com/x").mock(return_value=httpx.Response(500, text="boom"))
    r = await admin_client.post(
        "/api/v1/notify/channels",
        json={"name": "hook", "type": "webhook", "config": {"url": "https://hook.example.com/x"}},
    )
    r = await admin_client.post(f"/api/v1/notify/channels/{r.json()['id']}/test")
    assert r.json()["ok"] is False and "500" in r.json()["error"]
