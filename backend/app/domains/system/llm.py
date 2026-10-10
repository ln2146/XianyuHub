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
from app.domains.system.models import AuditLog, LlmProvider, LlmTierBinding
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
        "id": "custom",
        "name": "自定义配置",
        "kind": "openai_compatible",
        "base_url": "",
        "models": {"vision": "", "chat": "", "fast": ""},
        "suggested_models": [],
        "note": "手动填写任意接口地址、API Key 与模型名",
        "category": "custom",
    },
    {
        "id": "deepseek",
        "name": "DeepSeek",
        "kind": "openai_compatible",
        "base_url": "https://api.deepseek.com/v1",
        "models": {"vision": "", "chat": "deepseek-chat", "fast": "deepseek-chat"},
        "suggested_models": ["deepseek-chat", "deepseek-reasoner"],
        "note": "高性价比对话与推理主力，适合客服回复与意图分类",
        "category": "cn",
    },
    {
        "id": "dashscope",
        "name": "阿里百炼 (通义千问)",
        "kind": "openai_compatible",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "models": {"vision": "qwen-vl-max", "chat": "qwen-plus", "fast": "qwen-turbo"},
        "suggested_models": ["qwen-plus", "qwen-max", "qwen-turbo", "qwen-vl-max", "qwen-vl-plus", "qwen-flash"],
        "note": "国内直连稳定，qwen-vl-max 识图精准，适合看图发品与质检",
        "category": "cn",
    },
    {
        "id": "openai",
        "name": "OpenAI Official",
        "kind": "openai_compatible",
        "base_url": "https://api.openai.com/v1",
        "models": {"vision": "gpt-4o", "chat": "gpt-4o", "fast": "gpt-4o-mini"},
        "suggested_models": ["gpt-4o", "gpt-4o-mini", "o1", "o3-mini", "gpt-4-turbo"],
        "note": "行业标准模型，gpt-4o 全模态视觉与指令遵循极高",
        "category": "global",
    },
    {
        "id": "claude",
        "name": "Claude Official",
        "kind": "anthropic",
        "base_url": "",
        "models": {
            "vision": "claude-3-7-sonnet-20250219",
            "chat": "claude-3-5-sonnet-20241022",
            "fast": "claude-3-5-haiku-20241022",
        },
        "suggested_models": [
            "claude-3-7-sonnet-20250219",
            "claude-3-5-sonnet-20241022",
            "claude-3-5-haiku-20241022",
            "claude-3-opus-20240229",
        ],
        "note": "Anthropic 官方原生接口，长文本与逻辑能力顶级，支持拒答回退",
        "category": "global",
    },
    {
        "id": "gemini",
        "name": "Google Gemini",
        "kind": "openai_compatible",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "models": {"vision": "gemini-2.0-flash", "chat": "gemini-2.0-flash", "fast": "gemini-2.0-flash-lite"},
        "suggested_models": [
            "gemini-2.0-flash",
            "gemini-2.0-pro-exp",
            "gemini-2.0-flash-lite",
            "gemini-1.5-pro",
            "gemini-1.5-flash",
        ],
        "note": "Google 官方 OpenAI 兼容端点，多模态推理快，上下文超长",
        "category": "global",
    },
    {
        "id": "zhipu",
        "name": "智谱 GLM",
        "kind": "openai_compatible",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "models": {"vision": "glm-4v-plus", "chat": "glm-4-plus", "fast": "glm-4-flash"},
        "suggested_models": ["glm-4-plus", "glm-4-flash", "glm-4-air", "glm-4v-plus", "glm-4v"],
        "note": "国产全自研，glm-4v 支持图像识别，glm-4-flash 免费额度高",
        "category": "cn",
    },
    {
        "id": "doubao",
        "name": "字节豆包 (火山引擎)",
        "kind": "openai_compatible",
        "base_url": "https://ark.cn-beijing.volces.com/api/v3",
        "models": {"vision": "doubao-vision-pro", "chat": "doubao-pro-32k", "fast": "doubao-lite-32k"},
        "suggested_models": ["doubao-pro-32k", "doubao-lite-32k", "doubao-vision-pro", "doubao-1.5-pro-32k"],
        "note": "字节跳动自研大模型，响应极快，超低延迟与综合成本极佳",
        "category": "cn",
    },
    {
        "id": "moonshot",
        "name": "月之暗面 Kimi",
        "kind": "openai_compatible",
        "base_url": "https://api.moonshot.cn/v1",
        "models": {"vision": "moonshot-v1-8k-vision-preview", "chat": "moonshot-v1-32k", "fast": "moonshot-v1-8k"},
        "suggested_models": ["moonshot-v1-8k", "moonshot-v1-32k", "moonshot-v1-128k", "moonshot-v1-8k-vision-preview"],
        "note": "长文本上下文能力强，适合闲鱼商品详细描述与咨询解析",
        "category": "cn",
    },
    {
        "id": "minimax",
        "name": "MiniMax (海螺)",
        "kind": "openai_compatible",
        "base_url": "https://api.minimax.chat/v1",
        "models": {"vision": "MiniMax-VL-01", "chat": "MiniMax-Text-01", "fast": "abab6.5s-chat"},
        "suggested_models": ["MiniMax-Text-01", "MiniMax-VL-01", "abab6.5s-chat", "abab6.5g-chat"],
        "note": "中文拟人度高，适合拟人化买卖家交流谈判与议价",
        "category": "cn",
    },
    {
        "id": "qianfan",
        "name": "百度千帆",
        "kind": "openai_compatible",
        "base_url": "https://qianfan.baidubce.com/v2",
        "models": {"vision": "ernie-4.0-turbo-8k", "chat": "ernie-4.0-turbo-8k", "fast": "ernie-speed-128k"},
        "suggested_models": ["ernie-4.0-turbo-8k", "ernie-speed-128k", "ernie-lite-8k", "ernie-novel-8k"],
        "note": "百度千帆兼容接口，中文语境与知识沉淀深厚",
        "category": "cn",
    },
    {
        "id": "stepfun",
        "name": "阶跃星辰 StepFun",
        "kind": "openai_compatible",
        "base_url": "https://api.stepfun.com/v1",
        "models": {"vision": "step-1v-8k", "chat": "step-1-32k", "fast": "step-1-8k"},
        "suggested_models": ["step-1-32k", "step-1-8k", "step-1v-8k", "step-2-16k"],
        "note": "阶跃星辰自研，step-1v 多模态识图与视觉细节敏锐",
        "category": "cn",
    },
    {
        "id": "siliconflow",
        "name": "硅基流动 SiliconFlow",
        "kind": "openai_compatible",
        "base_url": "https://api.siliconflow.cn/v1",
        "models": {
            "vision": "Qwen/Qwen2.5-VL-72B-Instruct",
            "chat": "deepseek-ai/DeepSeek-V3",
            "fast": "Qwen/Qwen2.5-7B-Instruct",
        },
        "suggested_models": [
            "deepseek-ai/DeepSeek-V3",
            "deepseek-ai/DeepSeek-R1",
            "Qwen/Qwen2.5-72B-Instruct",
            "Qwen/Qwen2.5-VL-72B-Instruct",
        ],
        "note": "聚合国内外主流开源大模型，高并发按需计费",
        "category": "aggregator",
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
        "suggested_models": [
            "anthropic/claude-sonnet-4.5",
            "openai/gpt-4o",
            "google/gemini-2.5-flash",
            "openai/gpt-4o-mini",
            "deepseek/deepseek-chat",
        ],
        "note": "一个 Key 自由调用全球主流厂商模型",
        "category": "aggregator",
    },
    {
        "id": "ollama",
        "name": "Ollama (本地私有)",
        "kind": "openai_compatible",
        "base_url": "http://127.0.0.1:11434/v1",
        "models": {"vision": "qwen2.5vl:7b", "chat": "qwen2.5:14b", "fast": "qwen2.5:7b"},
        "suggested_models": ["qwen2.5:14b", "qwen2.5:7b", "qwen2.5vl:7b", "deepseek-r1:8b"],
        "note": "本机本地运行，数据不出内网，API Key 留空或随意填",
        "category": "local",
    },
    {
        "id": "vllm",
        "name": "vLLM / 自建网关",
        "kind": "openai_compatible",
        "base_url": "http://127.0.0.1:8000/v1",
        "models": {"vision": "", "chat": "", "fast": ""},
        "suggested_models": [],
        "note": "兼容 /chat/completions 的企业私有或自建 API 端点",
        "category": "local",
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


async def get_tier_bindings(session: AsyncSession) -> dict[str, dict[str, Any]]:
    rows = (await session.execute(select(LlmTierBinding))).scalars().all()
    return {r.tier: {"provider_id": r.provider_id, "model": r.model} for r in rows}


async def set_tier_bindings(session: AsyncSession, bindings: dict[str, dict[str, Any]]) -> None:
    for tier_name in ("chat", "vision", "fast"):
        item = bindings.get(tier_name)
        if item is None:
            continue
        provider_id = item.get("provider_id")
        model = item.get("model") or ""
        row = (
            await session.execute(select(LlmTierBinding).where(LlmTierBinding.tier == tier_name))
        ).scalar_one_or_none()
        if row is None:
            row = LlmTierBinding(tier=tier_name, provider_id=provider_id, model=model)
            session.add(row)
        else:
            row.provider_id = provider_id
            row.model = model
    await session.commit()


async def load_active_config() -> LlmConfig | None:
    async with session_factory()() as session:
        tier_targets: dict[str, dict[str, Any]] = {}
        bindings = (await session.execute(select(LlmTierBinding))).scalars().all()
        if bindings:
            prov_ids = [b.provider_id for b in bindings if b.provider_id]
            if prov_ids:
                p_rows = (
                    await session.execute(
                        select(LlmProvider).where(LlmProvider.id.in_(prov_ids), LlmProvider.enabled.is_(True))
                    )
                ).scalars().all()
                prov_map = {p.id: p for p in p_rows}
                for b in bindings:
                    if b.provider_id and b.provider_id in prov_map:
                        p = prov_map[b.provider_id]
                        key = get_vault().decrypt(p.api_key_enc) or ""
                        model = b.model or getattr(p, f"model_{b.tier}", "")
                        if model:
                            tier_targets[b.tier] = {
                                "provider_id": p.id,
                                "provider_name": p.name,
                                "kind": p.kind,
                                "base_url": p.base_url,
                                "api_key": key,
                                "model": model,
                                "timeout": p.timeout_seconds,
                                "fallbacks": p.anthropic_fallbacks,
                            }

        active_p = await active_row(session)
        if active_p is not None:
            base = row_config(active_p)
            base.tier_targets = tier_targets
            return base

        if tier_targets:
            first = tier_targets.get("chat") or next(iter(tier_targets.values()))
            settings = get_settings()
            return LlmConfig(
                kind=first["kind"],
                api_key=first["api_key"],
                base_url=first["base_url"],
                model_vision=tier_targets.get("vision", {}).get("model", ""),
                model_chat=tier_targets.get("chat", {}).get("model", ""),
                model_fast=tier_targets.get("fast", {}).get("model", ""),
                timeout=float(first.get("timeout", settings.llm_timeout_seconds)),
                fallbacks=bool(first.get("fallbacks", True)),
                daily_token_budget=settings.llm_daily_token_budget,
                max_images=settings.llm_max_images,
                source="场景自选模型",
                tier_targets=tier_targets,
            )

        return None


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
    for tier in ("chat", "vision", "fast"):
        model = getattr(row, f"model_{tier}", "")
        if model:
            b = (
                await session.execute(select(LlmTierBinding).where(LlmTierBinding.tier == tier))
            ).scalar_one_or_none()
            if b is None:
                b = LlmTierBinding(tier=tier, provider_id=row.id, model=model)
                session.add(b)
            else:
                b.provider_id = row.id
                b.model = model
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
        if not config.api_key:
            raise LLMError("请先填写 API Key（Anthropic 需鉴权后获取可用模型）")
        return await _list_anthropic_models(config)

    if not config.base_url:
        raise LLMError("请先填写接口地址")
    if not config.api_key:
        raise LLMError("请先填写 API Key（服务商需鉴权后才能返回可用模型列表）")

    base = config.base_url.strip().rstrip("/")
    headers = {"Authorization": f"Bearer {config.api_key}"}

    candidates: list[str] = []
    if base.endswith("/v1"):
        candidates.append(f"{base}/models")
        candidates.append(f"{base[:-3]}/models")
    else:
        candidates.append(f"{base}/models")
        candidates.append(f"{base}/v1/models")

    # 去重保留候选顺序
    seen_urls: set[str] = set()
    uniq_candidates = [u for u in candidates if not (u in seen_urls or seen_urls.add(u))]

    last_error = ""
    auth_failed = False

    async with httpx.AsyncClient(timeout=20, follow_redirects=True) as http:
        for url in uniq_candidates:
            try:
                resp = await http.get(url, headers=headers)
            except httpx.RequestError as exc:
                last_error = f"网络连接失败：{exc}"
                continue

            if resp.status_code in (401, 403):
                auth_failed = True
                last_error = f"鉴权失败（HTTP {resp.status_code}），请检查 API Key 是否有效"
                break

            if resp.status_code == 404:
                last_error = "服务商未提供在线模型列表端点（HTTP 404）"
                continue

            if resp.status_code >= 400:
                last_error = f"接口返回 HTTP {resp.status_code}：{resp.text[:200]}"
                continue

            try:
                data = resp.json()
            except Exception:
                continue

            rows = data.get("data") if isinstance(data, dict) else data
            if not isinstance(rows, list):
                continue
            ids = [str(r.get("id") or r.get("name") or "").strip() for r in rows if isinstance(r, dict)]
            models = sorted({i for i in ids if i})
            if models:
                return models

    if auth_failed:
        raise LLMError(last_error)
    if last_error:
        raise LLMError(f"{last_error}，请直接在下方快捷选择推荐模型或手动添加")
    raise LLMError("接口未返回可用模型列表，请直接在下方快捷选择推荐模型或手动添加")


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
    "get_tier_bindings",
    "list_remote_models",
    "load_active_config",
    "mask_key",
    "refresh",
    "row_config",
    "seed_from_env",
    "set_tier_bindings",
    "test_connection",
]
