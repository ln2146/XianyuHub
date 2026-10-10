"""LLM 网关：多供应商、结构化输出、用量统计与预算控制。

- anthropic：官方 Python SDK（AsyncAnthropic），结构化输出用 output_config.format，
  默认开启服务端拒答回退（fallbacks="default"）
- openai_compatible：通义千问 / DeepSeek / vLLM 等 OpenAI 兼容接口（httpx）

生效配置（LlmConfig）优先取管理台里启用的「模型接入」，没有时回退到 LLM_* 环境变量；
管理台改动后由 app.domains.system.llm 调用 set_config() 触发网关重建。

调用方只关心 tier（vision / chat / fast）和输出的 Pydantic 模型；
网关不可用或超出预算时抛出 LLMUnavailable，调用方应降级为仅规则。
"""

import asyncio
import base64
import json
import os
import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Any, Literal, Protocol, TypeVar

import httpx
from loguru import logger
from pydantic import BaseModel, ValidationError

from app.core.config import Settings, get_settings

T = TypeVar("T", bound=BaseModel)
Effort = Literal["low", "medium", "high"]

# 建立连接单独限时：连不上时尽快报错，而不是等满整个生成超时（或系统 TCP 超时，约 70 秒）
CONNECT_TIMEOUT_SECONDS = 10.0


def _timeout(seconds: float) -> httpx.Timeout:
    return httpx.Timeout(seconds, connect=min(seconds, CONNECT_TIMEOUT_SECONDS))


class Tier(StrEnum):
    VISION = "vision"
    CHAT = "chat"
    FAST = "fast"


class LLMUnavailable(Exception):
    pass


class LLMError(Exception):
    pass


@dataclass
class ImageInput:
    url: str | None = None
    data: bytes | None = None
    media_type: str = "image/jpeg"

    def b64(self) -> str:
        assert self.data is not None
        return base64.standard_b64encode(self.data).decode("ascii")


@dataclass
class Message:
    role: Literal["user", "assistant"]
    content: str


@dataclass
class LLMResult:
    text: str
    model: str
    input_tokens: int = 0
    output_tokens: int = 0
    refused: bool = False


@dataclass
class Usage:
    day: date = field(default_factory=date.today)
    calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    by_tier: dict[str, int] = field(default_factory=dict)

    @property
    def total(self) -> int:
        return self.input_tokens + self.output_tokens


@dataclass
class LlmConfig:
    """一次调用所需的完整模型配置：数据库中的接入配置，或回退的环境变量。"""

    kind: str = "anthropic"  # anthropic / openai_compatible
    api_key: str = ""
    base_url: str = ""
    model_vision: str = ""  # 多模态判定、商品文案
    model_chat: str = ""  # 客服回复
    model_fast: str = ""  # 意图分类、粗筛
    timeout: float = 90.0
    fallbacks: bool = True
    daily_token_budget: int = 0  # 0 表示不限制
    max_images: int = 4
    source: str = "env"  # env 或 接入名称，仅用于界面展示
    tier_targets: dict[str, dict[str, Any]] = field(default_factory=dict)

    @classmethod
    def from_settings(cls, s: Settings) -> "LlmConfig":
        return cls(
            kind=s.llm_default_provider,
            api_key=s.llm_api_key,
            base_url=s.llm_base_url,
            model_vision=s.llm_model_vision,
            model_chat=s.llm_model_chat,
            model_fast=s.llm_model_fast,
            timeout=s.llm_timeout_seconds,
            fallbacks=s.llm_anthropic_fallbacks,
            daily_token_budget=s.llm_daily_token_budget,
            max_images=s.llm_max_images,
            source="env",
        )

    def model_for(self, tier: Tier) -> str:
        tier_key = tier.value if isinstance(tier, Tier) else str(tier)
        if tier_key in self.tier_targets and self.tier_targets[tier_key].get("model"):
            return self.tier_targets[tier_key]["model"]
        return {Tier.VISION: self.model_vision, Tier.CHAT: self.model_chat, Tier.FAST: self.model_fast}.get(tier, "")


class Provider(Protocol):
    async def complete(
        self,
        *,
        model: str,
        system: str,
        messages: Sequence[Message],
        images: Sequence[ImageInput],
        schema: dict[str, Any] | None,
        max_tokens: int,
        effort: Effort | None,
    ) -> LLMResult: ...


# ---------------------------------------------------------------------------- schema
def strict_schema(model: type[BaseModel]) -> dict[str, Any]:
    """把 Pydantic JSON Schema 调整为结构化输出要求的严格形式：
    所有对象 additionalProperties=false，所有属性 required。"""
    schema = model.model_json_schema()

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if node.get("type") == "object" and "properties" in node:
                node["additionalProperties"] = False
                node["required"] = list(node["properties"].keys())
            for key in ("default", "title"):
                node.pop(key, None)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    return schema


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.MULTILINE)


def parse_json(text: str) -> Any:
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    cleaned = _FENCE.sub("", text).strip()
    start, end = cleaned.find("{"), cleaned.rfind("}")
    if start >= 0 and end > start:
        return json.loads(cleaned[start : end + 1])
    raise LLMError(f"模型输出不是合法 JSON：{text[:200]}")


# ---------------------------------------------------------------------------- providers
class AnthropicProvider:
    """Claude（官方 SDK）。"""

    def __init__(self, api_key: str, base_url: str | None, timeout: float, fallbacks: bool) -> None:
        import anthropic

        self._anthropic = anthropic
        connect = min(timeout, CONNECT_TIMEOUT_SECONDS)
        kwargs: dict[str, Any] = {"timeout": anthropic.Timeout(timeout, connect=connect), "max_retries": 2}
        if api_key:
            kwargs["api_key"] = api_key
        if base_url:
            kwargs["base_url"] = base_url
        self.client = anthropic.AsyncAnthropic(**kwargs)
        # 自定义 base_url（代理 / 网关）可能不支持 fallbacks，此时不发送
        self.fallbacks = fallbacks and not base_url

    async def aclose(self) -> None:
        await self.client.close()

    async def complete(self, *, model, system, messages, images, schema, max_tokens, effort) -> LLMResult:
        content_last: list[dict[str, Any]] = []
        for img in images:
            if img.data is not None:
                content_last.append(
                    {"type": "image", "source": {"type": "base64", "media_type": img.media_type, "data": img.b64()}}
                )
            elif img.url:
                content_last.append({"type": "image", "source": {"type": "url", "url": img.url}})
        api_messages: list[dict[str, Any]] = []
        for i, m in enumerate(messages):
            if i == len(messages) - 1 and m.role == "user" and content_last:
                api_messages.append({"role": "user", "content": [*content_last, {"type": "text", "text": m.content}]})
            else:
                api_messages.append({"role": m.role, "content": m.content})

        output_config: dict[str, Any] = {}
        if effort:
            output_config["effort"] = effort
        if schema is not None:
            output_config["format"] = {"type": "json_schema", "schema": schema}
        kwargs: dict[str, Any] = {
            "model": model,
            "max_tokens": max_tokens,
            "system": system,
            "messages": api_messages,
        }
        if output_config:
            kwargs["output_config"] = output_config
        a = self._anthropic
        try:
            if self.fallbacks:
                resp = await self.client.beta.messages.create(
                    betas=["server-side-fallback-2026-07-01"], fallbacks="default", **kwargs
                )
            else:
                resp = await self.client.messages.create(**kwargs)
        except a.RateLimitError as e:
            raise LLMError(f"Claude 限流：{e.message}") from e
        except (a.AuthenticationError, a.PermissionDeniedError) as e:
            raise LLMUnavailable(f"Claude 鉴权失败：{e.message}") from e
        except a.BadRequestError as e:
            raise LLMError(f"Claude 请求错误：{e.message}") from e
        except a.APIStatusError as e:
            raise LLMError(f"Claude 接口错误 {e.status_code}：{e.message}") from e
        except a.APIConnectionError as e:
            raise LLMError("Claude 网络错误") from e

        refused = resp.stop_reason == "refusal"
        text = "".join(getattr(b, "text", "") for b in resp.content if b.type == "text")
        return LLMResult(
            text=text,
            model=resp.model,
            input_tokens=resp.usage.input_tokens or 0,
            output_tokens=resp.usage.output_tokens or 0,
            refused=refused,
        )


class ChatCompletionsProvider:
    """OpenAI 兼容的 /chat/completions 接口（通义千问、DeepSeek、vLLM 等）。"""

    def __init__(self, api_key: str, base_url: str, timeout: float, transport: httpx.AsyncBaseTransport | None = None):
        if not base_url:
            raise LLMUnavailable("openai_compatible 需要配置 LLM_BASE_URL")
        self.base_url = base_url.rstrip("/")
        self.http = httpx.AsyncClient(
            timeout=_timeout(timeout),
            transport=transport,
            headers={"Authorization": f"Bearer {api_key}"} if api_key else {},
        )
        self._json_mode = True

    async def aclose(self) -> None:
        await self.http.aclose()

    async def complete(self, *, model, system, messages, images, schema, max_tokens, effort) -> LLMResult:
        sys_text = system
        if schema is not None:
            sys_text += "\n\n只输出一个 JSON 对象，不要输出其他内容。JSON Schema：\n" + json.dumps(
                schema, ensure_ascii=False
            )
        api_messages: list[dict[str, Any]] = [{"role": "system", "content": sys_text}]
        for i, m in enumerate(messages):
            if i == len(messages) - 1 and m.role == "user" and images:
                parts: list[dict[str, Any]] = [{"type": "text", "text": m.content}]
                for img in images:
                    url = img.url if img.data is None else f"data:{img.media_type};base64,{img.b64()}"
                    parts.append({"type": "image_url", "image_url": {"url": url}})
                api_messages.append({"role": "user", "content": parts})
            else:
                api_messages.append({"role": m.role, "content": m.content})
        body: dict[str, Any] = {"model": model, "messages": api_messages, "max_tokens": max_tokens, "temperature": 0.2}
        if schema is not None and self._json_mode:
            body["response_format"] = {"type": "json_object"}
        resp = await self._post(body)
        if resp.status_code == 400 and "response_format" in body:
            # 部分网关不支持 json_object，降级为纯提示词约束
            self._json_mode = False
            body.pop("response_format")
            resp = await self._post(body)
        if resp.status_code in (401, 403):
            raise LLMUnavailable(f"模型接口鉴权失败：HTTP {resp.status_code}")
        if resp.status_code >= 400:
            raise LLMError(f"模型接口错误 HTTP {resp.status_code}：{resp.text[:200]}")
        try:
            data = resp.json()
            text = data["choices"][0]["message"].get("content") or ""
        except (ValueError, KeyError, IndexError, TypeError, AttributeError) as e:
            raise LLMError(f"模型接口返回格式异常：{resp.text[:200]}") from e
        usage = data.get("usage") or {}
        return LLMResult(
            text=text,
            model=data.get("model", model),
            input_tokens=usage.get("prompt_tokens", 0),
            output_tokens=usage.get("completion_tokens", 0),
        )

    async def _post(self, body: dict[str, Any]) -> httpx.Response:
        """网络层错误（超时、连接断开等）统一转成 LLMError，调用方据此降级，而不是整条流程失败。
        连接没建立起来时请求还没到服务端，重试一次是安全的，能挡掉偶发的网络抖动。"""
        url = f"{self.base_url}/chat/completions"
        try:
            try:
                return await self.http.post(url, json=body)
            except (httpx.ConnectError, httpx.ConnectTimeout) as e:
                logger.warning("模型接口连接失败，重试一次：{}", type(e).__name__)
                return await self.http.post(url, json=body)
        except httpx.HTTPError as e:
            raise LLMError(f"模型接口网络错误：{type(e).__name__} {e}".strip()) from e


# ---------------------------------------------------------------------------- gateway
class LLMGateway:
    def __init__(
        self, provider: Provider | None = None, config: LlmConfig | None = None, usage: Usage | None = None
    ) -> None:
        self.config = config or get_config()
        # 进程默认网关共享同一份用量统计：切换 / 编辑模型配置不会清零当日用量，也就不能借此绕过每日预算
        self.usage = usage if usage is not None else Usage()
        self._provider = provider
        self._tier_providers: dict[str, Provider] = {}
        self._init_error: str | None = None
        if provider is None:
            try:
                self._provider = self._build_provider_from_config(self.config)
            except LLMUnavailable as e:
                self._init_error = str(e)
            except Exception as e:  # noqa: BLE001
                self._init_error = f"LLM 初始化失败：{e}"

            for tier_name, target in self.config.tier_targets.items():
                try:
                    p = self._build_provider_from_target(target)
                    if p is not None:
                        self._tier_providers[tier_name] = p
                except Exception as e:  # noqa: BLE001
                    logger.warning("Tier {} 提供商初始化失败: {}", tier_name, e)

    def _build_provider_from_config(self, c: LlmConfig) -> Provider:
        if c.kind == "anthropic":
            if not (c.api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                raise LLMUnavailable("未配置 LLM_API_KEY")
            return AnthropicProvider(c.api_key, c.base_url or None, c.timeout, c.fallbacks)
        if c.kind == "openai_compatible":
            return ChatCompletionsProvider(c.api_key, c.base_url, c.timeout)
        raise LLMUnavailable(f"未知的 LLM 供应商：{c.kind}")

    def _build_provider_from_target(self, target: dict[str, Any]) -> Provider | None:
        kind = target.get("kind") or "openai_compatible"
        api_key = target.get("api_key") or ""
        base_url = target.get("base_url") or ""
        timeout = float(target.get("timeout") or self.config.timeout)
        fallbacks = bool(target.get("fallbacks", True))
        if kind == "anthropic":
            if not (api_key or os.environ.get("ANTHROPIC_API_KEY") or os.environ.get("ANTHROPIC_AUTH_TOKEN")):
                return None
            return AnthropicProvider(api_key, base_url or None, timeout, fallbacks)
        if kind == "openai_compatible":
            if not base_url:
                return None
            return ChatCompletionsProvider(api_key, base_url, timeout)
        return None

    def _provider_for(self, tier: Tier) -> Provider | None:
        tier_key = tier.value if isinstance(tier, Tier) else str(tier)
        return self._tier_providers.get(tier_key) or self._provider

    async def aclose(self) -> None:
        providers = set()
        if self._provider is not None:
            providers.add(self._provider)
        for p in self._tier_providers.values():
            providers.add(p)
        for p in providers:
            close = getattr(p, "aclose", None)
            if close is not None:
                try:
                    await close()
                except Exception:  # noqa: BLE001
                    logger.debug("关闭模型客户端失败", exc_info=True)

    @property
    def available(self) -> bool:
        has_any = self._provider is not None or bool(self._tier_providers)
        return has_any and not self._over_budget()

    def status(self) -> dict[str, Any]:
        return {
            "available": self.available,
            "provider": self.config.kind,
            "source": self.config.source,
            "error": self._init_error,
            "models": {t.value: self.model_for(t) for t in Tier},
            "tier_sources": {
                t.value: (
                    f"{self.config.tier_targets[t.value].get('provider_name', '')} ({self.model_for(t)})"
                    if t.value in self.config.tier_targets and self.config.tier_targets[t.value].get("provider_name")
                    else f"{self.config.source} ({self.model_for(t)})"
                )
                for t in Tier
            },
            "usage_today": {
                "calls": self.usage.calls,
                "input_tokens": self.usage.input_tokens,
                "output_tokens": self.usage.output_tokens,
                "budget": self.config.daily_token_budget,
            },
        }

    def model_for(self, tier: Tier) -> str:
        return self.config.model_for(tier)

    def _over_budget(self) -> bool:
        if self.usage.day != date.today():
            self.usage.__init__()  # 原地重置，保持共享引用
        budget = self.config.daily_token_budget
        return bool(budget) and self.usage.total >= budget

    async def _complete(
        self,
        tier: Tier,
        system: str,
        messages: Sequence[Message],
        images: Sequence[ImageInput],
        schema: dict[str, Any] | None,
        max_tokens: int,
        effort: Effort | None,
    ) -> LLMResult:
        provider = self._provider_for(tier)
        if provider is None:
            raise LLMUnavailable(self._init_error or f"未配置 {tier.value} 对应的大模型接入")
        if self._over_budget():
            raise LLMUnavailable("今日大模型 token 预算已用完")
        model = self.model_for(tier)
        if not model:
            raise LLMUnavailable(f"未配置 {tier.value} 场景的模型名称")
        result = await provider.complete(
            model=model,
            system=system,
            messages=messages,
            images=list(images)[: self.config.max_images],
            schema=schema,
            max_tokens=max_tokens,
            effort=effort,
        )
        self.usage.calls += 1
        self.usage.input_tokens += result.input_tokens
        self.usage.output_tokens += result.output_tokens
        self.usage.by_tier[tier] = self.usage.by_tier.get(tier, 0) + result.input_tokens + result.output_tokens
        if result.refused:
            raise LLMError("模型拒绝回答该请求")
        return result

    async def complete_json(
        self,
        tier: Tier,
        system: str,
        user: str | Sequence[Message],
        output: type[T],
        *,
        images: Sequence[ImageInput] = (),
        max_tokens: int = 4000,
        effort: Effort | None = None,
    ) -> T:
        messages = [Message("user", user)] if isinstance(user, str) else list(user)
        schema = strict_schema(output)
        last_error: Exception | None = None
        for _ in range(2):  # 解析失败重试一次
            result = await self._complete(tier, system, messages, images, schema, max_tokens, effort)
            try:
                return output.model_validate(parse_json(result.text))
            except (LLMError, ValidationError, json.JSONDecodeError) as e:
                last_error = e
                logger.warning("LLM 结构化输出解析失败，重试：{}", e)
        raise LLMError(f"结构化输出解析失败：{last_error}")

    async def complete_text(
        self,
        tier: Tier,
        system: str,
        messages: Sequence[Message],
        *,
        images: Sequence[ImageInput] = (),
        max_tokens: int = 1000,
        effort: Effort | None = None,
    ) -> str:
        result = await self._complete(tier, system, messages, images, None, max_tokens, effort)
        return result.text.strip()


_gateway: LLMGateway | None = None
_config: LlmConfig | None = None
_shared_usage = Usage()
_retiring: set[asyncio.Task] = set()


def _retire(gateway: LLMGateway) -> None:
    """配置切换后延迟关闭旧网关的 HTTP 客户端，给进行中的请求留出完成时间。"""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return

    def _close() -> None:
        task = loop.create_task(gateway.aclose())
        _retiring.add(task)
        task.add_done_callback(_retiring.discard)

    loop.call_later(gateway.config.timeout + 30, _close)


def get_config() -> LlmConfig:
    """当前生效的模型配置：管理台接入配置优先，其次环境变量。"""
    return _config or LlmConfig.from_settings(get_settings())


def set_config(config: LlmConfig | None) -> None:
    """替换生效配置并重建网关。config 为空表示回退到环境变量。"""
    global _config, _gateway
    old = _gateway
    _config = config
    _gateway = None
    if old is not None:
        _retire(old)


def get_llm() -> LLMGateway:
    global _gateway
    if _gateway is None:
        _gateway = LLMGateway(usage=_shared_usage)
    return _gateway


def set_llm(gateway: LLMGateway | None) -> None:
    """测试时替换网关；传 None 同时清空共享用量。"""
    global _gateway
    _gateway = gateway
    if gateway is None:
        _shared_usage.__init__()
