"""安全回归：上传与外链导入的资源限制、SSRF、越权写操作、异常令牌。"""

import io

import httpx
import jwt
import pytest
import respx

from app.core.config import get_settings
from app.core.db import session_factory
from app.domains.account.models import XyAccount
from app.domains.message import knowledge

JPEG = b"\xff\xd8\xff\xe0" + b"0" * 100


async def _member_headers(admin_client, username="kefu"):
    await admin_client.post("/api/v1/users", json={"username": username, "password": "kefu-pass-1"})
    r = await admin_client.post(
        "/api/v1/auth/login", json={"username": username, "password": "kefu-pass-1"}, headers={"Authorization": ""}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


async def test_image_upload_checks_real_format_and_size(admin_client, monkeypatch):
    # 声明是 PNG、内容其实是 HTML：按文件头识别，拒绝
    r = await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.png", b"<html>hi</html>", "image/png")})
    assert r.status_code == 400
    ok = await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.bin", JPEG, "application/octet-stream")})
    assert ok.status_code == 200 and ok.json()["id"].endswith(".jpg")

    from app.domains.goods import service as goods_service

    monkeypatch.setattr(goods_service, "MAX_IMAGE_BYTES", 50)
    big = await admin_client.post("/api/v1/goods/uploads", files={"file": ("a.jpg", JPEG, "image/jpeg")})
    assert big.status_code == 400 and "10MB" in big.json()["detail"]


@respx.mock
async def test_image_url_import_only_fetches_goofish_images(admin_client):
    for url in (
        "http://127.0.0.1:8001/api/v1/users",
        "https://169.254.169.254/latest/meta-data",
        "https://evil.example.com/a.jpg",
        "https://alicdn.com.evil.example/a.jpg",
        "file:///etc/passwd",
    ):
        r = await admin_client.post("/api/v1/goods/import-image-url", json={"url": url})
        assert r.status_code == 400 and "闲鱼商品图片" in r.json()["detail"], url

    # 允许的域名也不跟随重定向（防止跳转到内网）
    respx.get("https://img.alicdn.com/jump.jpg").mock(
        return_value=httpx.Response(302, headers={"location": "http://127.0.0.1/admin"})
    )
    r = await admin_client.post("/api/v1/goods/import-image-url", json={"url": "https://img.alicdn.com/jump.jpg"})
    assert r.status_code == 400
    # 内容不是图片
    respx.get("https://img.alicdn.com/page.jpg").mock(return_value=httpx.Response(200, content=b"<html></html>"))
    r = await admin_client.post("/api/v1/goods/import-image-url", json={"url": "https://img.alicdn.com/page.jpg"})
    assert r.status_code == 400 and "不是" in r.json()["detail"]
    # 正常的闲鱼图片（含协议相对地址）
    respx.get("https://img.alicdn.com/ok.jpg").mock(return_value=httpx.Response(200, content=JPEG))
    r = await admin_client.post("/api/v1/goods/import-image-url", json={"url": "//img.alicdn.com/ok.jpg"})
    assert r.status_code == 200 and r.json()["id"].endswith(".jpg")


async def test_document_upload_size_limit_and_off_loop_parsing(admin_client, monkeypatch):
    monkeypatch.setattr(knowledge, "MAX_FILE_BYTES", 10)
    from app.domains.message import router as message_router

    monkeypatch.setattr(message_router, "MAX_FILE_BYTES", 10)
    r = await admin_client.post("/api/v1/messages/knowledge-docs", files={"file": ("a.txt", b"x" * 100, "text/plain")})
    assert r.status_code == 400 and "50MB" in r.json()["detail"]
    monkeypatch.undo()
    # 解析在后台线程执行，结果一致
    assert await knowledge.extract_text_async("a.txt", "发货说明".encode()) == "发货说明"


async def test_docx_zip_bomb_is_rejected(monkeypatch):
    import zipfile

    import pytest

    monkeypatch.setattr(knowledge, "MAX_DOCX_UNZIPPED", 1000)
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("word/document.xml", "0" * 100_000)  # 压缩后很小、解压后很大
    with pytest.raises(knowledge.UnsupportedFile, match="解压后过大"):
        knowledge.extract_text("a.docx", buf.getvalue())


async def test_polish_all_only_touches_permitted_accounts(admin_client, monkeypatch):
    from app.domains.goods import service as goods_service

    calls = []

    async def fake_polish_all(account_id=None, only_accounts=None):
        calls.append((account_id, only_accounts))
        return 0

    monkeypatch.setattr(goods_service, "polish_all", fake_polish_all)
    async with session_factory()() as s:
        s.add(XyAccount(owner_id=1, unb="9001", device_id="d"))  # 管理员的账号
        await s.commit()
        admin_acc = (await s.execute(XyAccount.__table__.select())).first().id
    h = await _member_headers(admin_client)
    r = await admin_client.post(f"/api/v1/goods/polish-all?account_id={admin_acc}", headers=h)
    assert r.status_code == 404  # 不能擦亮别人的账号
    r = await admin_client.post("/api/v1/goods/polish-all", headers=h)
    assert r.status_code == 200
    import asyncio

    await asyncio.sleep(0)
    assert calls[-1] == (None, [])  # 不指定账号：只处理自己有权限的（这里一个都没有）


async def test_signed_token_with_bad_payload_is_401_not_500(client):
    secret = get_settings().app_secret_key
    for payload in ({}, {"sub": "abc"}, {"sub": None}, {"sub": "1" * 400}):
        token = jwt.encode(payload, secret, algorithm="HS256")
        r = await client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
        assert r.status_code == 401, payload


async def test_price_history_and_ai_insight_are_per_user(admin_client):
    from datetime import UTC, datetime

    from app.domains.buyer.models import ItemInsightRecord, PriceSnapshot, PriceWatch

    now = datetime.now(UTC)
    ai = {
        "item_summary": "s",
        "seller_summary": "s",
        "ip_assessment": "s",
        "comment_insight": "s",
        "seller_type": "personal",
        "trust_level": "high",
        "advice": "可以买",
        "questions_for_seller": [],
    }
    async with session_factory()() as s:
        s.add(PriceSnapshot(item_id="880001", price=100, seen_at=now))
        s.add(ItemInsightRecord(owner_id=1, item_id="880001", ai_data=ai, created_at=now, updated_at=now))
        await s.commit()
    h = await _member_headers(admin_client)
    # 别人关注的商品：成员看不到价格走势，也看不到管理员保存的 AI 点评
    assert (await admin_client.get("/api/v1/buyer/items/880001/prices", headers=h)).status_code == 404
    assert (await admin_client.get("/api/v1/buyer/items/880001/insight", headers=h)).json() is None
    from app.domains.buyer.router import _own_insight
    from app.domains.system.models import User

    async with session_factory()() as s:
        admin, member = await s.get(User, 1), (await s.execute(User.__table__.select().where(User.id != 1))).first()
        assert (await _own_insight(s, admin, "880001")).ai_data["advice"] == "可以买"
        assert await _own_insight(s, await s.get(User, member.id), "880001") is None
    # 成员自己也在价格监控里关注了这件：可以看价格走势
    member_id = (await admin_client.get("/api/v1/auth/me", headers=h)).json()["id"]
    async with session_factory()() as s:
        s.add(PriceWatch(owner_id=member_id, item_id="880001", title="x", interval_minutes=60))
        await s.commit()
    r = await admin_client.get("/api/v1/buyer/items/880001/prices", headers=h)
    assert r.status_code == 200 and r.json()[0]["price"] == 100


async def test_readyz_checks_the_database(client):
    r = await client.get("/readyz")
    assert r.status_code == 200 and r.json()["checks"]["database"] == "ok"
    assert (await client.get("/healthz")).json() == {"status": "ok"}


async def test_negative_pagination_is_rejected(admin_client):
    for path in ("/api/v1/orders", "/api/v1/messages/conversations", "/api/v1/buyer/results", "/api/v1/audit-logs"):
        assert (await admin_client.get(f"{path}?offset=-1")).status_code == 422, path
        assert (await admin_client.get(f"{path}?limit=0")).status_code == 422, path


def test_any_non_dev_app_env_counts_as_production():
    from app.core.config import Settings

    for env in ("production", "Production", "prod", "staging", " PRODUCTION "):
        assert Settings(app_env=env).is_production, env
    for env in ("development", "dev", "Local", "test"):
        assert not Settings(app_env=env).is_production, env


async def _two_accounts(admin_client):
    """管理员名下账号 1，成员 kefu 名下账号 2；返回成员的请求头。"""
    h = await _member_headers(admin_client)
    async with session_factory()() as s:
        s.add_all([XyAccount(owner_id=1, unb="1", device_id="d1"), XyAccount(owner_id=2, unb="2", device_id="d2")])
        await s.commit()
    return h


async def test_member_cannot_move_draft_or_task_to_others_account(admin_client):
    h = await _two_accounts(admin_client)
    draft = {"account_id": 2, "title": "t", "desc": "d", "image_ids": ["x"], "price": 1}
    created = await admin_client.post("/api/v1/goods/drafts", json=draft, headers=h)
    assert created.status_code == 201
    r = await admin_client.put(
        f"/api/v1/goods/drafts/{created.json()['id']}", json={**draft, "account_id": 1}, headers=h
    )
    assert r.status_code == 404
    task = {"name": "t", "keywords": ["a"], "account_id": 1}
    assert (await admin_client.post("/api/v1/buyer/tasks", json=task, headers=h)).status_code == 404
    own = await admin_client.post("/api/v1/buyer/tasks", json={**task, "account_id": 2}, headers=h)
    assert own.status_code == 201
    r = await admin_client.put(f"/api/v1/buyer/tasks/{own.json()['id']}", json=task, headers=h)
    assert r.status_code == 404


async def test_scheduled_draft_is_not_published_without_creator_access(admin_client):
    from app.domains.goods import service as goods_service
    from app.domains.goods.models import DraftStatus, PublishDraftRecord

    await _two_accounts(admin_client)
    async with session_factory()() as s:
        d = PublishDraftRecord(account_id=1, title="t", desc="d", image_ids=["x"], price=1, created_by=2)
        s.add(d)
        await s.commit()
        draft_id = d.id
    with pytest.raises(ValueError, match="无权"):
        await goods_service.publish_draft(draft_id)
    async with session_factory()() as s:
        assert (await s.get(PublishDraftRecord, draft_id)).status == DraftStatus.FAILED


async def test_netguard_blocks_metadata_and_member_private_targets():
    from app.core.netguard import UnsafeTargetError, check_url

    await check_url("https://8.8.8.8/x")
    await check_url("http://192.168.1.10:8080/hook", allow_private=True)  # 管理员可以指向局域网服务
    await check_url("http://nas.local/hook", allow_private=True)
    for url in (
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://[::1]/",
        "http://[::ffff:192.168.0.1]/",
        "http://0.0.0.0/",
    ):
        with pytest.raises(UnsafeTargetError):
            await check_url(url)
    for url in ("http://169.254.169.254/latest/meta-data/", "http://[fe80::1]/", "ftp://example.com/"):
        with pytest.raises(UnsafeTargetError):
            await check_url(url, allow_private=True)  # 元数据地址和非 http 协议管理员也不行


async def test_member_cannot_point_outbound_requests_at_internal_network(admin_client):
    from app.domains.order.service import DeliveryError, call_delivery_api

    h = await _member_headers(admin_client)
    hook = {"name": "h", "type": "webhook", "config": {"url": "http://127.0.0.1:8000/api/v1/users"}}
    r = await admin_client.post("/api/v1/notify/channels", json=hook, headers=h)
    assert r.status_code == 400 and "内网" in r.json()["detail"]
    probe = (await admin_client.post("/api/v1/notify/test", json=hook, headers=h)).json()
    assert probe["ok"] is False and "内网" in probe["error"]
    pool = {"name": "p", "kind": "api", "api_config": {"url": "http://10.0.0.8/secret"}}
    assert (await admin_client.post("/api/v1/cards/pools", json=pool, headers=h)).status_code == 400
    # 管理员可以用局域网地址，但云主机元数据地址谁都不行
    assert (await admin_client.post("/api/v1/cards/pools", json=pool)).status_code == 201
    meta = {**pool, "api_config": {"url": "http://169.254.169.254/latest/meta-data/"}}
    assert (await admin_client.post("/api/v1/cards/pools", json=meta)).status_code == 400
    # 发货时再校验一次（地址可能是旧数据，或域名解析结果已变化）
    with pytest.raises(DeliveryError, match="内网"):
        await call_delivery_api({"url": "http://127.0.0.1/x"}, None)
