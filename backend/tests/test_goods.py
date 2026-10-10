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
    detail = respx.post(url__regex=r".*mtop\.taobao\.idle\.pc\.detail.*").mock(
        return_value=ok({"itemDO": {"itemId": 701, "wantCnt": 3, "browseCnt": 420, "gmtCreate": 1759900000000}})
    )
    r = await admin_client.post(f"/api/v1/goods/accounts/{acc_id}/sync")
    # 同步后补全在售商品的数据（已售的不查）
    assert r.json() == {"total": 2, "created": 2, "updated": 0, "stats": 1}
    assert detail.call_count == 1
    items = (await admin_client.get("/api/v1/goods/items?status=on_sale")).json()
    assert [i["item_id"] for i in items] == ["701"]
    assert items[0]["want_cnt"] == 3 and items[0]["browse_cnt"] == 420
    assert items[0]["publish_time"] and items[0]["stats_at"]

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


NEARBY = {
    "address": "南京东路 1 号",
    "area": "黄浦区",
    "city": "上海",
    "divisionId": 310101,
    "latitude": "31.234",
    "longitude": "121.475",
    "poi": "人民广场",
    "poiId": "B00155FAKE",
    "prov": "上海",
}


@respx.mock
async def test_pick_item_location_and_reuse_it(admin_client):
    acc_id = await make_account(admin_client)
    poi = respx.post(url__regex=r".*local\.poi\.get.*").mock(
        return_value=ok({"commonAddresses": [], "nearbyAddresses": [NEARBY, {"poi": "缺字段"}]})
    )
    r = await admin_client.get(f"/api/v1/goods/locations?account_id={acc_id}&longitude=121.47&latitude=31.23")
    assert r.status_code == 200, r.text
    assert r.json()["saved"] is None and r.json()["nearby"][0]["poiId"] == "B00155FAKE"
    assert len(r.json()["nearby"]) == 1  # 字段不全的地点被丢弃
    req = poi.calls[0].request
    # 不带发布页 spm 时闲鱼只返回空对象
    assert req.headers["eagleeye-userdata"] == "spm-cnt=a21ybx" and "spm_cnt=a21ybx.publish.0.0" in str(req.url)

    image_id = (await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()[
        "id"
    ]
    draft = {"account_id": acc_id, "title": "测试", "desc": "测试", "image_ids": [image_id], "price": 10}
    location = r.json()["nearby"][0]
    d1 = (await admin_client.post("/api/v1/goods/drafts", json={**draft, "location": location})).json()
    assert d1["location"]["poi"] == "人民广场"

    respx.post("https://stream-upload.goofish.com/api/upload.api").mock(
        return_value=httpx.Response(200, json={"object": {"url": "https://img.alicdn.com/x.png", "pix": "800x600"}})
    )
    respx.post(url__regex=r".*kgraph\.property\.recommend.*").mock(
        return_value=ok({"categoryPredictResult": {"catId": 1, "catName": "x", "channelCatId": 2, "tbCatId": 3}})
    )
    publish = respx.post(url__regex=r".*idleitem\.publish.*").mock(return_value=ok({"itemId": "880002"}))
    before = poi.call_count
    assert (await admin_client.post(f"/api/v1/goods/drafts/{d1['id']}/publish")).status_code == 200
    sent = json.loads(dict(httpx.QueryParams(publish.calls[0].request.content.decode()))["data"])
    addr = json.dumps(sent, ensure_ascii=False)
    assert "B00155FAKE" in addr and "310101" in addr and "121.475,31.234" in addr
    assert poi.call_count == before  # 选了所在地就不再去查常用地址

    # 下一份草稿不选所在地：沿用上次的
    saved = (await admin_client.get(f"/api/v1/goods/locations?account_id={acc_id}")).json()["saved"]
    assert saved["poiId"] == "B00155FAKE"
    d2 = (await admin_client.post("/api/v1/goods/drafts", json=draft)).json()
    publish.mock(return_value=ok({"itemId": "880003"}))
    assert (await admin_client.post(f"/api/v1/goods/drafts/{d2['id']}/publish")).status_code == 200
    assert "B00155FAKE" in dict(httpx.QueryParams(publish.calls[-1].request.content.decode()))["data"]
    assert poi.call_count == before

    # 账号没通过闲鱼发布认证：给出能照着做的提示，而不是接口原文
    d3 = (await admin_client.post("/api/v1/goods/drafts", json=draft)).json()
    publish.mock(
        return_value=httpx.Response(
            200, json={"ret": ["FAIL_BIZ_STRONG_VALID_VERIFY_INFO::用户未通过认证"], "data": {}}
        )
    )
    r = await admin_client.post(f"/api/v1/goods/drafts/{d3['id']}/publish")
    assert r.status_code == 428 and "身份认证" in r.json()["detail"] and "FAIL_BIZ" not in r.json()["detail"]
    # 认证二维码与网页版发布页相同：经 sharexy 中转后在闲鱼 App 打开认证页
    verify = r.headers["x-verify-url"]
    assert verify.startswith("https://pages.goofish.com/sharexy?") and "fleamarket%3A%2F%2Fidentity_auth" in verify
    # 失败的草稿认证后可以直接重新发布
    publish.mock(return_value=ok({"itemId": "880004"}))
    assert (await admin_client.post(f"/api/v1/goods/drafts/{d3['id']}/publish")).json()["item_id"] == "880004"


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


@respx.mock
async def test_multi_inventory_blocked_before_upload_when_account_lacks_it(admin_client):
    acc_id = await make_account(admin_client)
    respx.post(url__regex=r".*prepublish\.check.*").mock(return_value=ok({"limited": False}))
    pre = respx.post(url__regex=r".*idleitem\.preget.*").mock(return_value=ok({"supportSkuOrInventory": False}))
    meta = (await admin_client.get(f"/api/v1/goods/publish-meta?account_id={acc_id}")).json()
    assert meta["support_inventory"] is False and meta["limited"] is False

    upload = respx.post("https://stream-upload.goofish.com/api/upload.api").mock(
        return_value=httpx.Response(200, json={"object": {"url": "https://img.alicdn.com/x.png", "pix": "8x6"}})
    )
    publish = respx.post(url__regex=r".*idleitem\.publish.*").mock(return_value=ok({"itemId": "1"}))
    image_id = (await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", PNG, "image/png")})).json()[
        "id"
    ]
    draft = {"account_id": acc_id, "title": "资料", "desc": "资料", "image_ids": [image_id], "price": 1, "quantity": 5}
    d = (await admin_client.post("/api/v1/goods/drafts", json=draft)).json()
    r = await admin_client.post(f"/api/v1/goods/drafts/{d['id']}/publish")
    assert r.status_code == 409 and "数量改成 1" in r.json()["detail"]
    assert not upload.called and not publish.called

    # 支持多库存的账号照常发布
    pre.mock(return_value=ok({"supportSkuOrInventory": True}))
    respx.post(url__regex=r".*kgraph\.property\.recommend.*").mock(
        return_value=ok({"categoryPredictResult": {"catId": 1, "catName": "x", "channelCatId": 2, "tbCatId": 3}})
    )
    respx.post(url__regex=r".*local\.poi\.get.*").mock(
        return_value=ok({"commonAddresses": [{"city": "上海", "prov": "上海", "area": "浦东", "divisionId": 1}]})
    )
    assert (await admin_client.post(f"/api/v1/goods/drafts/{d['id']}/publish")).status_code == 200


@respx.mock
async def test_import_image_url(admin_client):
    respx.get("https://img.alicdn.com/test.png").mock(
        return_value=httpx.Response(200, content=PNG, headers={"content-type": "image/png"})
    )
    r = await admin_client.post("/api/v1/goods/import-image-url", json={"url": "https://img.alicdn.com/test.png"})
    assert r.status_code == 200
    data = r.json()
    assert "id" in data
    assert data["url"] == f"/api/v1/goods/uploads/{data['id']}"

    img_resp = await admin_client.get(data["url"])
    assert img_resp.status_code == 200
    assert img_resp.content == PNG


@respx.mock
async def test_polish_all_endpoint(admin_client):
    acc_id = await make_account(admin_client)
    respx.post(url__regex=r".*mtop\.taobao\.idle\.item\.polish.*").mock(return_value=ok({}))
    r = await admin_client.post(f"/api/v1/goods/polish-all?account_id={acc_id}")
    assert r.status_code == 200
    assert "启动" in r.json()["message"]
