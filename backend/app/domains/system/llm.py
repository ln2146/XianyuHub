"""大模型接入配置：管理台可维护的多套配置，随时切换生效。

- 配置落库（api_key 用 Vault 加密），同一时刻只有一套 enabled + is_active 的配置生效
- 没有任何生效配置时回退到 LLM_* 环境变量，行为与旧版本一致
- 切换或保存后刷新进程内网关；分离部署时通过事件总线通知 Worker 一起刷新
"""

from typing import Any

import httpx
from loguru import logger
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.crypto import get_vault
from app.core.db import session_factory
from app.core.events import Topics, bus
from app.domains.system.models import AuditLog, LlmProvider
from app.intelligence.llm import (
    LlmConfig,
    LLMError,
    LLMGateway,
    Message,
    Tier,
    set_config,
)

# 常见供应商预设：填写 API Key 即可用；base_url 与模型名都可以再改
PRESETS: list[dict[str, Any]] = [
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "kind": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "models": {"vision": "", "chat": "deepseek-chat", "fast": "deepseek-chat"},
        "note": "适合客服回复与意图分类",
    },
    {
        "id": "dashscope",
        "name": "通义千问（阿里云百炼）",
        "kind": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": {"vision": "qwen-vl-max", "chat": "qwen-plus", "fast": "qwen-turbo"},
        "note": "国内直连，qwen-vl 系列支持图片",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "kind": "openai_compatible",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": {"vision": "glm-4v-plus", "chat": "glm-4-plus", "fast": "glm-4-flash"},
        "note": "glm-4v 支持图片，glm-4-flash 免费额度较宽松",
    },
    {
        "id": "moonshot",
        "name": "月之暗面 Kimi",
        "kind": "openai_compatible",
        "base_url": "https://api.moonshot.cn/v1",
        "models": {"vision": "moonshot-v1-8k-vision-preview", "chat": "moonshot-v1-32k", "fast": "moonshot-v1-8k"},
        "note": "长文本理解好，适合商品描述与知识库问答",
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "kind": "openai_compatible",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": {
            "vision": "Qwen/Qwen2.5-VL-72B-Instruct",
            "chat": "Qwen/Qwen2.5-72B-Instruct",
            "fast": "Qwen/Qwen2.5-7B-Instruct",
        },
        "note": "聚合多种开源模型，可按价格挑模型",
    },
    {
        "id": "openrouter",
        "name": "OpenRouter",
        "kind": "openai_compatible",
        "base_url": "https://openrouter.ai/api/v1",
        "models": {
            "vision": "google/gemini-2.5-flash",
            "chat": "anthropic/claude-sonnet-4.5",
            "fast": "openai/gpt-4o-mini",
        },
        "note": "一个 Key 调用多家模型，便于对比效果",
    },
    {
        "id": "ollama",
        "name": "Ollama（本地）",
        "kind": "openai_compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "models": {"vision": "qwen2.5vl:7b", "chat": "qwen2.5:14b", "fast": "qwen2.5:7b"},
        "note": "本机运行，数据不出内网；API Key 随意填",
    },
    {
        "id": "vllm",
        "name": "vLLM / 自建网关",
        "kind": "openai_compatible",
        "base_url": "http://127.0.0.1:8000/v1",
        "models": {"vision": "", "chat": "", "fast": ""},
        "note": "兼容 /chat/completions 的任意自建服务",
    },
    {
        "id": "custom",
        "name": "自定义",
        "kind": "openai_compatible",
        "base_url": "",
        "models": {"vision": "", "chat": "", "fast": ""},
        "note": "手动填写接口地址与模型名",
    },
]


SEED_ACTION = "llm.provider.seed"  # 审计记录同时作为“已经初始化过”的标记


def mask_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 10:
        return "***"
    return f"{key[:6]}***{key[-4:]}"


def row_config(row: LlmProvider) -> LlmConfig:
    settings = get_settings()
    return LlmConfig(
        kind=row.kind,
        api_key=get_vault().decrypt(row.api_key_enc) or "",
        base_url=row.base_url or "",
        model_vision=row.model_vision or "",
        model_chat=row.model_chat or "",
        model_fast=row.model_fast or "",
        timeout=row.timeout_seconds or settings.llm_timeout_seconds,
        fallbacks=row.anthropic_fallbacks,
        daily_token_budget=(
            settings.llm_daily_token_budget if row.daily_token_budget is None else row.daily_token_budget
        ),
        max_images=settings.llm_max_images,
        source=row.name,
    )


def encode_key(plain: str) -> str:
    return get_vault().encrypt(plain) or ""


async def active_row(session: AsyncSession) -> LlmProvider | None:
    stmt = (
        select(LlmProvider)
        .where(LlmProvider.is_active.is_(True), LlmProvider.enabled.is_(True))
        .order_by(LlmProvider.id.desc())
    )
    return (await session.execute(stmt)).scalars().first()


async def load_active_config() -> LlmConfig | None:
    async with session_factory()() as session:
        row = await active_row(session)
        return row_config(row) if row is not None else None


async def apply_active_config() -> LlmConfig | None:
    """把数据库里生效的配置装载到网关；返回生效配置（None 表示回退环境变量）。"""
    config = await load_active_config()
    set_config(config)
    return config


async def refresh(notify: bool = True) -> LlmConfig | None:
    """配置变更后刷新网关，并通知其他进程（分离部署）。"""
    config = await apply_active_config()
    logger.info("大模型配置已生效：{}", config.source if config else "环境变量")
    if notify:
        await bus.publish(Topics.LLM_CONFIG_CHANGED, {"source": config.source if config else "env"})
    return config


async def activate(session: AsyncSession, row: LlmProvider) -> None:
    await session.execute(update(LlmProvider).values(is_active=False))
    row.is_active = True
    row.enabled = True
    await session.commit()


async def seed_from_env() -> None:
    """首次启动：把环境变量里的模型配置落成一套接入配置，方便在界面上直接改。"""
    settings = get_settings()
    if not settings.llm_api_key:
        return
    async with session_factory()() as session:
        exists = (await session.execute(select(LlmProvider.id))).scalars().first()
        seeded = (
            await session.execute(select(AuditLog.id).where(AuditLog.action == SEED_ACTION).limit(1))
        ).scalar_one_or_none()
        if exists is not None or seeded is not None:
            return
        row = LlmProvider(
            name="环境变量配置",
            kind=settings.llm_default_provider,
            base_url=settings.llm_base_url,
            api_key_enc=encode_key(settings.llm_api_key),
            model_vision=settings.llm_model_vision,
            model_chat=settings.llm_model_chat,
            model_fast=settings.llm_model_fast,
            timeout_seconds=settings.llm_timeout_seconds,
            anthropic_fallbacks=settings.llm_anthropic_fallbacks,
            enabled=True,
            is_active=True,
        )
        session.add(row)
        session.add(AuditLog(action=SEED_ACTION, actor_type="system", target_type="llm_provider", detail={}))
        await session.commit()
        logger.info("已根据环境变量创建大模型接入配置：{}", row.name)


# ---------------------------------------------------------------------------- 模型列表 / 连通性
def _candidate_models(config: LlmConfig) -> list[str]:
    return [m for m in (config.model_vision, config.model_chat, config.model_fast) if m]


async def list_remote_models(config: LlmConfig) -> list[str]:
    """尽力向供应商拉取可用模型列表；接口不支持时抛 LLMError，由调用方提示手填。"""
    if config.kind == "anthropic":
        return await _list_anthropic_models(config)
    else:
        if not config.base_url:
            raise LLMError("请先填写接口地址")
        url = f"{config.base_url.rstrip('/')}/models"
        headers = {"Authorization": f"Bearer {config.api_key}"} if config.api_key else {}
    async with httpx.AsyncClient(timeout=20) as http:
        resp = await http.get(url, headers=headers)
    if resp.status_code in (401, 403):
        raise LLMError(f"鉴权失败（HTTP {resp.status_code}），请检查 API Key")
    if resp.status_code >= 400:
        raise LLMError(f"接口返回 HTTP {resp.status_code}：{resp.text[:200]}")
    data = resp.json()
    rows = data.get("data") if isinstance(data, dict) else data
    if not isinstance(rows, list):
        raise LLMError("接口没有返回模型列表，请手动填写模型名")
    ids = [str(r.get("id") or r.get("name") or "").strip() for r in rows if isinstance(r, dict)]
    return sorted({i for i in ids if i})


async def _list_anthropic_models(config: LlmConfig) -> list[str]:
    """Claude 模型列表走官方 SDK（与调用路径一致）。"""
    import anthropic

    kwargs: dict[str, Any] = {"timeout": 20, "max_retries": 1}
    if config.api_key:
        kwargs["api_key"] = config.api_key
    if config.base_url:
        kwargs["base_url"] = config.base_url
    client = anthropic.AsyncAnthropic(**kwargs)
    try:
        return sorted({m.id async for m in client.models.list(limit=100)})
    except (anthropic.AuthenticationError, anthropic.PermissionDeniedError) as e:
        raise LLMError("鉴权失败，请检查 API Key") from e
    except anthropic.APIStatusError as e:
        raise LLMError(f"接口返回 HTTP {e.status_code}：{e.message}") from e
    except anthropic.APIConnectionError as e:
        raise LLMError("无法连接接口地址") from e
    finally:
        await client.close()


async def test_connection(config: LlmConfig) -> tuple[bool, str, str]:
    """用一次极小的调用验证 Key / 地址 / 模型是否可用，返回 (ok, 说明, 模型名)。"""
    model = config.model_fast or config.model_chat or config.model_vision
    if not model:
        return False, "请先填写至少一个模型名", ""
    gateway = LLMGateway(config=config)
    try:
        if not gateway.available:
            return False, gateway.status()["error"] or "配置不可用", model
        text = await gateway.complete_text(
            Tier.FAST,
            "你是连通性测试助手，只回答“ok”。",
            [Message("user", "ping")],
            max_tokens=256,  # 留出余量：部分模型会先输出思考内容
            effort="low",
        )
    except Exception as e:  # noqa: BLE001
        return False, (str(e) or type(e).__name__)[:300], model
    finally:
        await gateway.aclose()
    return True, f"调用成功：{text[:60] or '（空响应）'}", model


__all__ = [
    "PRESETS",
    "activate",
    "active_row",
    "apply_active_config",
    "encode_key",
    "list_remote_models",
    "load_active_config",
    "mask_key",
    "refresh",
    "row_config",
    "seed_from_env",
    "test_connection",
]
