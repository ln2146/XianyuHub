"""令牌桶限流：单机为进程内实现，多进程部署时使用 Redis（Lua 原子脚本）。"""

import asyncio
import time
from dataclasses import dataclass
from typing import Protocol


class RateLimiter(Protocol):
    async def reserve(
        self, key: str, rate: float, per: float, burst: float = 1, *, max_wait: float | None = None
    ) -> float:
        """返回所需等待秒数；超过 max_wait 时拒绝预占，不延长队列。"""
        ...


@dataclass
class _Bucket:
    tokens: float
    updated: float


class MemoryRateLimiter:
    def __init__(self) -> None:
        self._buckets: dict[str, _Bucket] = {}
        self._lock = asyncio.Lock()

    async def reserve(
        self, key: str, rate: float, per: float, burst: float = 1, *, max_wait: float | None = None
    ) -> float:
        refill = rate / per  # 每秒补充的令牌
        async with self._lock:
            now = time.monotonic()
            b = self._buckets.get(key)
            if b is None:
                b = _Bucket(tokens=burst, updated=now)
                self._buckets[key] = b
            b.tokens = min(burst, b.tokens + (now - b.updated) * refill)
            b.updated = now
            wait = max(0.0, (1 - b.tokens) / refill)
            if max_wait is None or wait <= max_wait:
                b.tokens -= 1  # 允许为负：表示排队中的预占
            return wait


_LUA = """
local key = KEYS[1]
local refill = tonumber(ARGV[1])
local burst = tonumber(ARGV[2])
local now = tonumber(ARGV[3])
local max_wait = tonumber(ARGV[4])
local data = redis.call('HMGET', key, 'tokens', 'updated')
local tokens = tonumber(data[1]) or burst
local updated = tonumber(data[2]) or now
tokens = math.min(burst, tokens + (now - updated) * refill)
local wait = math.max(0, (1 - tokens) / refill)
if max_wait < 0 or wait <= max_wait then tokens = tokens - 1 end
redis.call('HSET', key, 'tokens', tokens, 'updated', now)
redis.call('EXPIRE', key, 86400)
return tostring(wait)
"""


class RedisRateLimiter:
    def __init__(self, redis) -> None:  # redis.asyncio.Redis
        self._redis = redis
        self._script = redis.register_script(_LUA)

    async def reserve(
        self, key: str, rate: float, per: float, burst: float = 1, *, max_wait: float | None = None
    ) -> float:
        wait = await self._script(
            keys=[f"xyh:rl:{key}"], args=[rate / per, burst, time.time(), max_wait if max_wait is not None else -1]
        )
        return float(wait)
