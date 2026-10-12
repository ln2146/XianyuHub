"""可靠性回归：订单人工处理校验、卡密并发导入、草稿发布的原子领取与结果不确定。"""

import asyncio

import httpx
import respx

from app.core.db import session_factory
from app.domains.goods import service as goods_service
from app.domains.goods.models import PublishDraftRecord
from app.domains.order.models import Order
from tests.test_goods import PNG, make_account, ok


async def test_manual_resolve_only_accepts_known_actions(admin_client):
    acc_id = await make_account(admin_client)
    async with session_factory()() as s:
        o = Order(account_id=acc_id, order_id="5500001", status="manual")
        s.add(o)
        await s.commit()
        pk = o.id
    r = await admin_client.post(f"/api/v1/orders/{pk}/resolve-manual?action=cancel")
    assert r.status_code == 422  # 以前任何值都会把订单标成已发货
    r = await admin_client.post(f"/api/v1/orders/{pk}/resolve-manual?action=closed")
    assert r.status_code == 200 and r.json()["status"] == "closed"
    # 已关闭的订单不能再标记为已发货：明确报错，而不是悄悄返回成功
    r = await admin_client.post(f"/api/v1/orders/{pk}/resolve-manual?action=delivered")
    assert r.status_code == 409


async def test_concurrent_card_imports_do_not_duplicate(admin_client):
    pool = (await admin_client.post("/api/v1/cards/pools", json={"name": "p", "kind": "pool"})).json()
    lines = "\n".join(f"CODE-{i}" for i in range(20))
    results = await asyncio.gather(
        *[admin_client.post(f"/api/v1/cards/pools/{pool['id']}/items", json={"lines": lines}) for _ in range(3)]
    )
    assert all(r.status_code == 200 for r in results)
    stock = (await admin_client.get("/api/v1/cards/pools")).json()[0]["stock"]
    assert stock["available"] == 20
    assert sum(r.json()["added"] for r in results) == 20


async def _draft(admin_client, acc_id):
    image_id = (await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()[
        "id"
    ]
    draft = {"account_id": acc_id, "title": "测试", "desc": "测试", "image_ids": [image_id], "price": 10}
    return (await admin_client.post("/api/v1/goods/drafts", json=draft)).json()["id"]


def _mock_publish_prereqs():
    respx.post("https://stream-upload.goofish.com/api/upload.api").mock(
        return_value=httpx.Response(200, json={"object": {"url": "https://img.alicdn.com/x.png", "pix": "8x6"}})
    )
    respx.post(url__regex=r".*kgraph\.property\.recommend.*").mock(
        return_value=ok({"categoryPredictResult": {"catId": 1, "catName": "x", "channelCatId": 2, "tbCatId": 3}})
    )
    respx.post(url__regex=r".*local\.poi\.get.*").mock(
        return_value=ok({"commonAddresses": [{"city": "上海", "prov": "上海", "area": "浦东", "divisionId": 1}]})
    )


@respx.mock
async def test_same_draft_is_published_once_under_concurrency(admin_client):
    acc_id = await make_account(admin_client)
    draft_id = await _draft(admin_client, acc_id)
    _mock_publish_prereqs()
    publish = respx.post(url__regex=r".*idleitem\.publish.*").mock(return_value=ok({"itemId": "770001"}))
    results = await asyncio.gather(*[goods_service.publish_draft(draft_id) for _ in range(3)], return_exceptions=True)
    assert [r for r in results if r == "770001"] == ["770001"]
    assert all(isinstance(r, ValueError) for r in results if r != "770001")
    assert publish.call_count == 1


@respx.mock
async def test_publish_with_unknown_outcome_tells_seller_to_check_first(admin_client):
    acc_id = await make_account(admin_client)
    draft_id = await _draft(admin_client, acc_id)
    _mock_publish_prereqs()
    respx.post(url__regex=r".*idleitem\.publish.*").mock(side_effect=httpx.ReadTimeout("timeout"))
    r = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/publish")
    assert r.status_code >= 400
    async with session_factory()() as s:
        d = await s.get(PublishDraftRecord, draft_id)
        assert d.status == "unknown" and "可能已经上架" in d.error and "核对" in d.error
    before = respx.calls.call_count
    repeated = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/publish")
    assert repeated.status_code == 409 and "核对" in repeated.json()["detail"]
    assert respx.calls.call_count == before
    resolved = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/confirm-unpublished")
    assert resolved.status_code == 200 and resolved.json()["status"] == "draft"
