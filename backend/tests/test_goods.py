import json

import httpx
import respx
from sqlalchemy import select

from app.core.db import session_factory
from app.domains.goods.models import MyItem
from app.domains.system.models import AuditLog
from app.intelligence.llm import LLMGateway, LLMResult, set_llm
from tests.test_accounts import COOKIES, mock_probe

PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def ok(data):
    return httpx.Response(200, json={"ret": ["SUCCESS::ok"], "data": data})


async def make_account(client) -> int:
    mock_probe()
    return (await client.post("/api/v1/accounts/import", json={"cookies": COOKIES})).json()["id"]


@respx.mock
async def test_sync_items_and_floor_price(admin_client):
    acc_id = await make_account(admin_client)
    respx.post(url__regex=r".*xyh\.item\.list.*").mock(
        return_value=ok(
            {
                "nextPage": False,
                "cardList": [
                    {
                        "cardData": {
                            "id": "701",
                            "title": "Switch 日版",
                            "priceInfo": {"price": "1200"},
                            "itemStatus": 0,
                        }
                    },
                    {"cardData": {"id": "702", "title": "旧键盘", "priceInfo": {"price": "50"}, "itemStatus": 1}},
                ],
            }
        )
    )
    r = await admin_client.post(f"/api/v1/goods/accounts/{acc_id}/sync")
    assert r.json() == {"total": 2, "created": 2, "updated": 0}
    items = (await admin_client.get("/api/v1/goods/items?status=on_sale")).json()
    assert [i["item_id"] for i in items] == ["701"]

    r = await admin_client.patch(f"/api/v1/goods/items/{items[0]['id']}", json={"floor_price": 2000})
    assert r.status_code == 400
    r = await admin_client.patch(
        f"/api/v1/goods/items/{items[0]['id']}", json={"floor_price": 1050, "knowledge": "日版，带两个手柄"}
    )
    assert r.json()["floor_price"] == 1050
    async with session_factory()() as s:
        item = (await s.execute(select(MyItem).where(MyItem.item_id == "701"))).scalar_one()
        policy = item.bargain_policy()
        assert policy and policy.floor_price == 1050 and policy.list_price == 1200


@respx.mock
async def test_upload_draft_and_publish(admin_client):
    acc_id = await make_account(admin_client)
    r = await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})
    assert r.status_code == 200
    image_id = r.json()["id"]
    assert (await admin_client.get(r.json()["url"])).content == PNG
    bad = await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.txt", b"x", "text/plain")})
    assert bad.status_code == 400

    draft = {
        "account_id": acc_id,
        "title": "AirPods Pro 2",
        "desc": "自用半年，功能正常",
        "image_ids": [image_id],
        "price": 899,
        "floor_price": 820,
        "knowledge": "支持降噪",
    }
    r = await admin_client.post("/api/v1/goods/drafts", json={**draft, "floor_price": 999})
    assert r.status_code == 422
    r = await admin_client.post("/api/v1/goods/drafts", json=draft)
    assert r.status_code == 201 and r.json()["status"] == "draft"
    draft_id = r.json()["id"]

    upload = respx.post("https://stream-upload.goofish.com/api/upload.api").mock(
        return_value=httpx.Response(200, json={"object": {"url": "https://img.alicdn.com/x.png", "pix": "800x600"}})
    )
    respx.post(url__regex=r".*kgraph\.property\.recommend.*").mock(
        return_value=ok({"categoryPredictResult": {"catId": 1, "catName": "耳机", "channelCatId": 2, "tbCatId": 3}})
    )
    respx.post(url__regex=r".*local\.poi\.get.*").mock(
        return_value=ok({"commonAddresses": [{"city": "上海", "prov": "上海", "area": "浦东", "divisionId": 1}]})
    )
    publish = respx.post(url__regex=r".*idleitem\.publish.*").mock(return_value=ok({"itemId": "880001"}))

    r = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/publish")
    assert r.status_code == 200, r.text
    assert r.json()["item_id"] == "880001" and upload.called
    sent = json.loads(dict(httpx.QueryParams(publish.calls[0].request.content.decode()))["data"])
    assert sent["itemPriceDTO"]["priceInCent"] == "89900"
    assert sent["imageInfoDOList"][0]["url"] == "https://img.alicdn.com/x.png"

    drafts = (await admin_client.get("/api/v1/goods/drafts")).json()
    assert drafts[0]["status"] == "published"
    r = await admin_client.post(f"/api/v1/goods/drafts/{draft_id}/publish")
    assert r.status_code == 409
    async with session_factory()() as s:
        item = (await s.execute(select(MyItem).where(MyItem.item_id == "880001"))).scalar_one()
        assert item.floor_price == 820 and item.knowledge == "支持降噪"
        log = (await s.execute(select(AuditLog).where(AuditLog.action == "goods.publish"))).scalar_one()
        assert log.success and log.target_id == "880001"


@respx.mock
async def test_ai_copy_with_market(admin_client):
    image_id = (await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()[
        "id"
    ]

    class Fake:
        async def complete(self, **kw):
            assert kw["images"][0].data == PNG
            return LLMResult(
                text='{"titles":["AirPods Pro 2 自用"],"desc":"九成新","search_keyword":"airpods pro 2",'
                '"condition":"9成新","highlights":["降噪"]}',
                model="m",
            )

    set_llm(LLMGateway(provider=Fake()))
    respx.post(url__regex=r".*mtop\.gaia.*").mock(
        return_value=httpx.Response(200, json={"ret": ["SUCCESS"], "data": {}}, headers={"set-cookie": "_m_h5_tk=a_1"})
    )
    rows = [
        {"data": {"item": {"main": {"exContent": {"itemId": str(i), "title": "airpods", "price": [{"text": str(p)}]}}}}}
        for i, p in enumerate([700, 750, 800, 850, 900, 950])
    ]
    respx.post(url__regex=r".*idlemtopsearch.*").mock(return_value=ok({"resultList": rows}))
    r = await admin_client.post("/api/v1/goods/ai-copy", json={"image_ids": [image_id], "hint": "带盒"})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["titles"] and body["market"]["sample"] == 6
    assert body["market"]["suggestion"]["market"] == 825


@respx.mock
async def test_floor_price_can_be_cleared(admin_client):
    acc_id = await make_account(admin_client)
    async with session_factory()() as s:
        s.add(MyItem(account_id=acc_id, item_id="1", title="x", price=100, floor_price=80))
        await s.commit()
    items = (await admin_client.get("/api/v1/goods/items")).json()
    r = await admin_client.patch(f"/api/v1/goods/items/{items[0]['id']}", json={"floor_price": None, "gifts": "贴膜"})
    assert r.json()["floor_price"] is None and r.json()["gifts"] == "贴膜" and r.json()["max_rounds"] == 3
