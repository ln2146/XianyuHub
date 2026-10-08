"""运行时容器：风控守卫、闲鱼网关、Redis 等进程级单例。"""

from dataclasses import dataclass, field
from typing import Any

import httpx
from loguru import logger

from app.core.config import get_settings
from app.goofish.gateway import BrowserSearchChannel, GoofishGateway
from app.goofish.guard.guard import RiskGuard
from app.goofish.guard.limiter import MemoryRateLimiter, RedisRateLimiter


@dataclass
class AppRuntime:
    guard: RiskGuard
    gateway: GoofishGateway
    redis: Any = None
    extras: dict[str, Any] = field(default_factory=dict)


_runtime: AppRuntime | None = None


def get_runtime() -> AppRuntime:
    if _runtime is None:
        raise RuntimeError("运行时尚未初始化")
    return _runtime


async def init_runtime(transport: httpx.AsyncBaseTransport | None = None) -> AppRuntime:
    global _runtime
    from app.domains.account.store import DbSessionStore

    settings = get_settings()
    redis = None
    limiter: Any = MemoryRateLimiter()
    if settings.redis_url:
        import redis.asyncio as aioredis

        redis = aioredis.from_url(settings.redis_url, decode_responses=True)
        limiter = RedisRateLimiter(redis)
        logger.info("使用 Redis 限流")
    guard = RiskGuard(limiter, jitter=settings.guard_jitter_ms_max > 0)
    browser = BrowserSearchChannel(settings.browser_headless) if settings.browser_enabled else None
    gateway = GoofishGateway(DbSessionStore(), guard, browser=browser, transport=transport)
    _runtime = AppRuntime(guard=guard, gateway=gateway, redis=redis)
    return _runtime


async def close_runtime() -> None:
    global _runtime
    if _runtime is None:
        return
    await _runtime.gateway.aclose()
    if _runtime.gateway.browser is not None:
        await _runtime.gateway.browser.aclose()  # type: ignore[attr-defined]
    if _runtime.redis is not None:
        await _runtime.redis.aclose()
    _runtime = None
