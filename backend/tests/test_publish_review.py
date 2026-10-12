from datetime import UTC, datetime, timedelta

import httpx
import respx

from app.core.db import session_factory
from app.domains.goods.models import DraftStatus, PublishDraftRecord
from app.domains.goods.service import publish_due_drafts
from tests.test_goods import NEARBY, PNG, make_account, ok


async def make_review_draft(client):
    account = await make_account(client)
    image = (await client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()["id"]
    body = {"account_id": account, "title": "耳机", "desc": "自用，发票情况待核验", "image_ids": [image], "price": 100, "location": NEARBY}
    draft = (await client.post("/api/v1/goods/drafts", json=body)).json()
    async with session_factory()() as session:
        row = await session.get(PublishDraftRecord, draft["id"])
        row.ai_meta = {"uncertain": ["是否有发票", "是否维修过"]}
        await session.commit()
    return draft["id"], body


@respx.mock
async def test_direct_publish_blocks_unverified_facts_without_uploading(admin_client):
    draft_id, _ = await make_review_draft(admin_client)
    response = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/publish")
    assert response.status_code == 409
    assert "2 项" in response.json()["detail"] and "是否有发票" in response.json()["detail"]
    assert not any("upload.api" in str(call.request.url) for call in respx.calls)


@respx.mock
async def test_schedule_requires_all_facts_and_confirmation_survives_reload(admin_client):
    draft_id, body = await make_review_draft(admin_client)
    at = (datetime.now(UTC) + timedelta(hours=1)).isoformat()
    partial = {**body, "scheduled_at": at, "confirmed_facts": ["是否有发票"]}
    response = await admin_client.put(f"/api/v1/goods/drafts/{draft_id}", json=partial)
    assert response.status_code == 400 and "是否维修过" in response.json()["detail"]
    # 被拒绝的定时发布不会改变已保存的草稿。
    stored = (await admin_client.get("/api/v1/goods/drafts")).json()[0]
    assert stored["status"] == "draft" and stored["confirmed_facts"] == []
    body = {**partial, "confirmed_facts": ["是否有发票", "是否维修过"]}
    response = await admin_client.put(f"/api/v1/goods/drafts/{draft_id}", json=body)
    assert response.status_code == 200 and response.json()["status"] == "scheduled"
    stored = (await admin_client.get("/api/v1/goods/drafts")).json()[0]
    assert stored["confirmed_facts"] == body["confirmed_facts"]


@respx.mock
async def test_worker_rechecks_legacy_scheduled_draft(admin_client):
    draft_id, _ = await make_review_draft(admin_client)
    async with session_factory()() as session:
        draft = await session.get(PublishDraftRecord, draft_id)
        draft.status = DraftStatus.SCHEDULED
        draft.scheduled_at = datetime.now(UTC) - timedelta(minutes=1)
        await session.commit()
    await publish_due_drafts()
    stored = (await admin_client.get("/api/v1/goods/drafts")).json()[0]
    assert stored["status"] == "failed" and "未核验" in stored["error"]
    assert not any("upload.api" in str(call.request.url) for call in respx.calls)


@respx.mock
async def test_verified_draft_can_publish_and_unknown_facts_are_rejected(admin_client):
    draft_id, body = await make_review_draft(admin_client)
    response = await admin_client.put(f"/api/v1/goods/drafts/{draft_id}", json={**body, "confirmed_facts": ["过时核验项"]})
    assert response.status_code == 400
    response = await admin_client.put(
        f"/api/v1/goods/drafts/{draft_id}", json={**body, "confirmed_facts": ["是否有发票", "是否维修过"]}
    )
    assert response.status_code == 200
    respx.post("https://stream-upload.goofish.com/api/upload.api").mock(
        return_value=httpx.Response(200, json={"object": {"url": "https://img.alicdn.com/x.png", "pix": "800x600"}})
    )
    respx.post(url__regex=r".*kgraph\.property\.recommend.*").mock(
        return_value=ok({"categoryPredictResult": {"catId": 1, "channelCatId": 2, "tbCatId": 3}})
    )
    respx.post(url__regex=r".*idleitem\.publish.*").mock(return_value=ok({"itemId": "reviewed-item"}))
    response = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/publish")
    assert response.status_code == 200, response.text
    assert response.json()["item_id"] == "reviewed-item"
