import asyncio
from datetime import UTC, datetime, timedelta

import respx

from app.core.db import session_factory
from app.domains.goods import service
from app.domains.goods.models import PublishDraftRecord
from app.domains.order.models import CardPool
from tests.test_goods import NEARBY, PNG, make_account, ok
from tests.test_reliability import _mock_publish_prereqs


async def configured_draft(client, *, pool_enabled=True):
    account = await make_account(client)
    pool = (await client.post("/api/v1/cards/pools", json={"name": "教程", "kind": "text", "text": "领取说明", "enabled": pool_enabled})).json()
    image = (await client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()["id"]
    body = {"account_id": account, "title": "教程", "desc": "教程资料", "price": 10, "image_ids": [image], "location": NEARBY,
            "delivery_setup": {"pool_id": pool["id"], "auto_relist": True}}
    draft = (await client.post("/api/v1/goods/drafts", json=body)).json()
    _mock_publish_prereqs()
    remote = respx.post(url__regex=r".*idleitem\.publish.*").mock(return_value=ok({"itemId": "published-with-delivery"}))
    return draft["id"], pool["id"], remote


@respx.mock
async def test_partial_success_persists_and_can_be_repaired_without_republishing(admin_client):
    draft_id, pool_id, remote = await configured_draft(admin_client, pool_enabled=False)
    response = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/publish")
    assert response.status_code == 200, response.text
    assert response.json()["item_id"] == "published-with-delivery"
    setup = response.json()["delivery_setup"]
    assert setup["status"] == "error" and "停用" in setup["error"]
    stored = (await admin_client.get("/api/v1/goods/drafts")).json()[0]
    assert stored["status"] == "published" and stored["delivery_setup"] == setup
    async with session_factory()() as session:
        pool = await session.get(CardPool, pool_id)
        pool.enabled = True
        await session.commit()
    # 并发重复修复只产生一条关联，且不会再次触发闲鱼发布。
    results = await asyncio.gather(*[service.setup_draft_delivery(draft_id) for _ in range(3)])
    assert all(result["status"] == "linked" for result in results)
    response = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/delivery/retry")
    assert response.status_code == 200 and response.json()["delivery_setup"]["status"] == "linked"
    bindings = (await admin_client.get("/api/v1/cards/bindings")).json()
    assert len(bindings) == 1 and bindings[0]["pool_id"] == pool_id and bindings[0]["auto_relist"] is True
    assert remote.call_count == 1


@respx.mock
async def test_scheduled_publish_applies_saved_delivery_setup(admin_client):
    draft_id, pool_id, remote = await configured_draft(admin_client)
    async with session_factory()() as session:
        draft = await session.get(PublishDraftRecord, draft_id)
        draft.status = "scheduled"
        draft.scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    await service.publish_due_drafts()
    stored = (await admin_client.get("/api/v1/goods/drafts")).json()[0]
    assert stored["status"] == "published" and stored["delivery_setup"]["status"] == "linked"
    assert (await admin_client.get("/api/v1/cards/bindings")).json()[0]["pool_id"] == pool_id
    assert remote.call_count == 1


@respx.mock
async def test_delivery_setup_cannot_use_another_users_pool(admin_client):
    draft_id, pool_id, _ = await configured_draft(admin_client)
    other = (await admin_client.post('/api/v1/users', json={'username': 'other', 'password': 'other-test-pass-123'})).json()
    async with session_factory()() as session:
        pool = await session.get(CardPool, pool_id)
        pool.owner_id = other['id']
        await session.commit()
    draft = (await admin_client.get("/api/v1/goods/drafts")).json()[0]
    response = await admin_client.put(f"/api/v1/goods/drafts/{draft_id}", json=draft)
    assert response.status_code == 404
