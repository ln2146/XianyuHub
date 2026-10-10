"""大模型接入配置：管理台 CRUD、切换生效、连通性测试与环境变量回退。"""

import httpx
import respx

from app.domains.system import llm as llm_service
from app.intelligence.llm import LlmConfig, get_config, get_llm


def _provider_body(**over) -> dict:
    body = {
        "name": "DeepSeek",
        "kind": "openai_compatible",
        "base_url": "https://llm.example.com/v1",
        "api_key": "sk-secret-key-123456",
        "model_vision": "qwen-vl",
        "model_chat": "deepseek-chat",
        "model_fast": "deepseek-chat",
    }
    body.update(over)
    return body


async def test_meta_lists_presets(admin_client):
    r = await admin_client.get("/api/v1/llm/meta")
    assert r.status_code == 200
    data = r.json()
    ids = [p["id"] for p in data["presets"]]
    assert {"deepseek", "dashscope", "ollama", "custom"} <= set(ids)
    assert data["kinds"] == ["anthropic", "openai_compatible"]


async def test_status_falls_back_to_env(admin_client):
    r = await admin_client.get("/api/v1/llm/status")
    assert r.status_code == 200
    data = r.json()
    assert data["using_env"] is True and data["active_source"] == "env"
    assert data["gateway"]["provider"] == "anthropic"


async def test_provider_crud_and_activate(admin_client):
    r = await admin_client.post("/api/v1/llm/providers", json=_provider_body(activate=True))
    assert r.status_code == 201, r.text
    created = r.json()
    assert created["is_active"] is True and created["has_api_key"] is True
    # Key 只以打码形式返回
    assert "sk-secret-key-123456" not in r.text
    assert created["api_key_masked"].startswith("sk-sec") and created["api_key_masked"].endswith("3456")

    # 生效配置已装载进网关（未真的调用，只校验模型名与来源）
    config = get_config()
    assert config.kind == "openai_compatible" and config.source == "DeepSeek"
    assert get_llm().config.model_chat == "deepseek-chat"
    status = (await admin_client.get("/api/v1/llm/status")).json()
    assert status["using_env"] is False and status["active_source"] == "DeepSeek"
    assert status["config"]["model_fast"] == "deepseek-chat"

    # 回传打码值不会覆盖真实 Key
    r = await admin_client.patch(
        f"/api/v1/llm/providers/{created['id']}",
        json={"api_key": created["api_key_masked"], "name": "DeepSeek 主用"},
    )
    assert r.status_code == 200 and r.json()["name"] == "DeepSeek 主用"
    assert r.json()["api_key_masked"] == created["api_key_masked"]

    # 同名冲突（旧名称已改名，因此用当前名称验证）
    assert (
        await admin_client.post("/api/v1/llm/providers", json=_provider_body(name="DeepSeek 主用"))
    ).status_code == 409

    # 停用生效配置后回退环境变量
    r = await admin_client.patch(f"/api/v1/llm/providers/{created['id']}", json={"enabled": False})
    assert r.status_code == 200 and r.json()["is_active"] is False
    assert get_config().source == "env"

    # 停用的配置不能激活
    assert (await admin_client.post(f"/api/v1/llm/providers/{created['id']}/activate")).status_code == 400

    assert (await admin_client.delete(f"/api/v1/llm/providers/{created['id']}")).status_code == 204
    assert (await admin_client.get("/api/v1/llm/providers")).json() == []


async def test_activate_switches_between_two_providers(admin_client):
    a = (await admin_client.post("/api/v1/llm/providers", json=_provider_body(name="A", activate=True))).json()
    b = (
        await admin_client.post(
            "/api/v1/llm/providers",
            json=_provider_body(name="B", model_chat="qwen-plus", activate=True),
        )
    ).json()
    assert b["is_active"] is True
    rows = {p["name"]: p for p in (await admin_client.get("/api/v1/llm/providers")).json()}
    assert rows["A"]["is_active"] is False and rows["B"]["is_active"] is True
    assert get_config().model_chat == "qwen-plus"
    assert a["id"] != b["id"]


@respx.mock
async def test_connection_test_and_model_list(admin_client):
    respx.post("https://llm.example.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "model": "deepseek-chat",
                "choices": [{"message": {"content": "ok"}}],
                "usage": {"prompt_tokens": 4, "completion_tokens": 1},
            },
        )
    )
    respx.get("https://llm.example.com/v1/models").mock(
        return_value=httpx.Response(200, json={"data": [{"id": "deepseek-chat"}, {"id": "deepseek-reasoner"}]})
    )

    r = await admin_client.post("/api/v1/llm/test", json=_provider_body())
    assert r.status_code == 200 and r.json()["ok"] is True, r.text
    assert r.json()["model"] == "deepseek-chat"

    r = await admin_client.post("/api/v1/llm/models", json=_provider_body())
    assert r.json()["models"] == ["deepseek-chat", "deepseek-reasoner"]

    # 缺少 API Key 时返回友好 400 校验提示
    no_key_body = _provider_body()
    no_key_body["api_key"] = ""
    r_no_key = await admin_client.post("/api/v1/llm/models", json=no_key_body)
    assert r_no_key.status_code == 400 and "API Key" in r_no_key.text

    # 测试失败的配置会记下 last_error
    respx.post("https://llm.example.com/v1/chat/completions").mock(return_value=httpx.Response(401, text="bad key"))
    saved = (await admin_client.post("/api/v1/llm/providers", json=_provider_body(name="坏的"))).json()
    r = await admin_client.post("/api/v1/llm/test", json={"id": saved["id"]})
    assert r.status_code == 200 and r.json()["ok"] is False and "鉴权" in r.json()["message"]
    row = next(p for p in (await admin_client.get("/api/v1/llm/providers")).json() if p["id"] == saved["id"])
    assert row["last_test_ok"] is False and row["last_error"]


async def test_member_cannot_manage_providers(admin_client, client):
    await admin_client.post("/api/v1/users", json={"username": "kefu", "password": "kefu-pass-1"})
    token = (await client.post("/api/v1/auth/login", json={"username": "kefu", "password": "kefu-pass-1"})).json()[
        "access_token"
    ]
    headers = {"Authorization": f"Bearer {token}"}
    assert (await client.get("/api/v1/llm/providers", headers=headers)).status_code == 403
    assert (await client.get("/api/v1/llm/status", headers=headers)).status_code == 200
    assert (await client.post("/api/v1/llm/test", json=_provider_body(), headers=headers)).status_code == 403


async def test_row_config_decrypts_key(admin_client):
    await admin_client.post("/api/v1/llm/providers", json=_provider_body(activate=True))
    from app.core.db import session_factory

    async with session_factory()() as session:
        row = await llm_service.active_row(session)
        assert row is not None
        config = llm_service.row_config(row)
    assert config.api_key == "sk-secret-key-123456"
    assert config.source == "DeepSeek"
    assert isinstance(config, LlmConfig)


async def test_budget_override_and_clear(admin_client):
    created = (
        await admin_client.post("/api/v1/llm/providers", json=_provider_body(daily_token_budget=5000, activate=True))
    ).json()
    assert created["daily_token_budget"] == 5000
    assert get_config().daily_token_budget == 5000

    # 显式传 null 清空覆盖，回退到全局设置
    r = await admin_client.patch(f"/api/v1/llm/providers/{created['id']}", json={"daily_token_budget": None})
    assert r.status_code == 200 and r.json()["daily_token_budget"] is None
    assert get_config().daily_token_budget == 0

    # 不传该字段时保持原值
    r = await admin_client.patch(f"/api/v1/llm/providers/{created['id']}", json={"model_fast": "other-model"})
    assert r.json()["daily_token_budget"] is None
    assert get_config().model_fast == "other-model"


async def test_usage_survives_config_switch():
    from app.intelligence.llm import LLMResult, Tier, get_llm, set_config

    gw = get_llm()

    class P:
        async def complete(self, **kw):
            return LLMResult(text="ok", model="m", input_tokens=7, output_tokens=3)

    gw._provider = P()
    await gw.complete_text(Tier.FAST, "s", [])
    assert gw.usage.total == 10
    # 切换配置会重建网关，但当日用量保留（不能靠切换绕过预算）
    set_config(LlmConfig(kind="openai_compatible", base_url="https://x/v1", model_fast="m", source="B"))
    assert get_llm() is not gw and get_llm().usage.total == 10


async def test_retired_gateway_client_is_closed(monkeypatch):
    import asyncio

    from app.intelligence import llm as llm_mod

    closed = []

    class P:
        async def aclose(self):
            closed.append(True)

    gw = llm_mod.LLMGateway(provider=P(), config=LlmConfig(timeout=0, source="x"))
    monkeypatch.setattr(llm_mod, "_gateway", gw)
    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "call_later", lambda delay, fn: fn())
    llm_mod.set_config(None)
    await asyncio.sleep(0)
    await asyncio.gather(*llm_mod._retiring)
    assert closed == [True]


async def test_seed_from_env_only_once(admin_client, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setenv("LLM_API_KEY", "sk-env-key-000000")
    get_settings.cache_clear()
    await llm_service.seed_from_env()
    rows = (await admin_client.get("/api/v1/llm/providers")).json()
    assert [r["name"] for r in rows] == ["环境变量配置"]
    await admin_client.delete(f"/api/v1/llm/providers/{rows[0]['id']}")
    # 管理员删掉后，再次启动不会重新生成
    await llm_service.seed_from_env()
    assert (await admin_client.get("/api/v1/llm/providers")).json() == []


async def test_anthropic_model_list_uses_sdk(monkeypatch):
    import anthropic

    seen = {}

    class FakeModels:
        async def _gen(self):
            for i in ("claude-opus-5-5", "claude-haiku-4-5"):
                yield type("M", (), {"id": i})()

        def list(self, **kw):
            seen["limit"] = kw.get("limit")
            return self._gen()

    class FakeClient:
        def __init__(self, **kw):
            seen["kwargs"] = kw
            self.models = FakeModels()

        async def close(self):
            seen["closed"] = True

    monkeypatch.setattr(anthropic, "AsyncAnthropic", FakeClient)
    models = await llm_service.list_remote_models(LlmConfig(kind="anthropic", api_key="sk-x"))
    assert models == ["claude-haiku-4-5", "claude-opus-5-5"]
    assert seen["kwargs"]["api_key"] == "sk-x" and seen["closed"]


@respx.mock
async def test_saved_key_never_sent_to_new_endpoint(admin_client):
    created = (await admin_client.post("/api/v1/llm/providers", json=_provider_body())).json()
    pid = created["id"]
    evil = respx.post("https://evil.example.com/v1/chat/completions").mock(return_value=httpx.Response(200))
    # 用已保存的 Key 测试新地址 → 拒绝，且不会发出请求
    r = await admin_client.post(
        "/api/v1/llm/test", json={**_provider_body(api_key=""), "id": pid, "base_url": "https://evil.example.com/v1"}
    )
    assert r.status_code == 400 and "重新填写 API Key" in r.json()["detail"]
    assert not evil.called
    r = await admin_client.post(
        "/api/v1/llm/models", json={**_provider_body(api_key=created["api_key_masked"]), "id": pid, "kind": "anthropic"}
    )
    assert r.status_code == 400
    # 只改地址不给新 Key → 拒绝；同时提供新 Key → 允许
    r = await admin_client.patch(f"/api/v1/llm/providers/{pid}", json={"base_url": "https://evil.example.com/v1"})
    assert r.status_code == 400
    r = await admin_client.patch(
        f"/api/v1/llm/providers/{pid}", json={"base_url": "https://new.example.com/v1", "api_key": "sk-new-key-999999"}
    )
    assert r.status_code == 200 and r.json()["base_url"] == "https://new.example.com/v1"
    # 地址不变（只差末尾斜杠）时照常复用已保存的 Key
    r = await admin_client.patch(
        f"/api/v1/llm/providers/{pid}", json={"base_url": "https://new.example.com/v1/", "model_chat": "x"}
    )
    assert r.status_code == 200


@respx.mock
async def test_tier_configuration_and_multi_provider_routing(admin_client):
    from app.intelligence.llm import Message, Tier

    # 接入两个不同的供应商
    p_deepseek = (
        await admin_client.post(
            "/api/v1/llm/providers",
            json={
                "name": "DeepSeek",
                "kind": "openai_compatible",
                "base_url": "https://api.deepseek.com/v1",
                "api_key": "sk-deepseek-123456",
                "model_chat": "deepseek-chat",
                "model_fast": "deepseek-chat",
                "model_vision": "",
            },
        )
    ).json()

    p_ali = (
        await admin_client.post(
            "/api/v1/llm/providers",
            json={
                "name": "Ali",
                "kind": "openai_compatible",
                "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
                "api_key": "sk-ali-654321",
                "model_vision": "qwen-vl-max",
                "model_chat": "qwen-plus",
                "model_fast": "qwen-turbo",
            },
        )
    ).json()

    # 配置场景绑定：chat -> DeepSeek, vision -> Ali, fast -> DeepSeek
    r = await admin_client.put(
        "/api/v1/llm/tiers",
        json={
            "chat": {"provider_id": p_deepseek["id"], "model": "deepseek-chat"},
            "vision": {"provider_id": p_ali["id"], "model": "qwen-vl-max"},
            "fast": {"provider_id": p_deepseek["id"], "model": "deepseek-chat"},
        },
    )
    assert r.status_code == 200
    tiers = r.json()["tiers"]
    assert tiers["chat"]["provider_id"] == p_deepseek["id"]
    assert tiers["vision"]["provider_id"] == p_ali["id"]

    # 检查 status 接口
    status = (await admin_client.get("/api/v1/llm/status")).json()
    assert status["tiers"]["vision"]["provider_id"] == p_ali["id"]
    assert status["gateway"]["models"]["vision"] == "qwen-vl-max"
    assert status["gateway"]["models"]["chat"] == "deepseek-chat"

    # 检查 list providers 返回每个供应商关联的激活场景
    providers = (await admin_client.get("/api/v1/llm/providers")).json()
    prov_map = {p["name"]: p for p in providers}
    assert "chat" in prov_map["DeepSeek"]["active_tiers"]
    assert "fast" in prov_map["DeepSeek"]["active_tiers"]
    assert "vision" in prov_map["Ali"]["active_tiers"]

    # Mock 外部请求并验证多路由分发
    ds_mock = respx.post("https://api.deepseek.com/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "你好，我是DeepSeek客服"}}],
                "usage": {"prompt_tokens": 10, "completion_tokens": 8},
            },
        )
    )
    ali_mock = respx.post("https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions").mock(
        return_value=httpx.Response(
            200,
            json={
                "choices": [{"message": {"role": "assistant", "content": "你好，我是通义万相视觉"}}],
                "usage": {"prompt_tokens": 15, "completion_tokens": 12},
            },
        )
    )

    gw = get_llm()
    # 场景1：客服对话 -> 应分发到 DeepSeek
    reply = await gw.complete_text(Tier.CHAT, "系统提示", [Message("user", "你好")])
    assert reply == "你好，我是DeepSeek客服"
    assert ds_mock.called
    assert not ali_mock.called

    # 场景2：看图视觉 -> 应分发到 Ali
    vision_reply = await gw.complete_text(Tier.VISION, "系统提示", [Message("user", "看图")])
    assert vision_reply == "你好，我是通义万相视觉"
    assert ali_mock.called
