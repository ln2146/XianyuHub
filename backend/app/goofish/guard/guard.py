"""风控守卫：所有对闲鱼的调用都必须经过这里。

- 账号状态检查（熔断 / 冷却 / 需要登录）
- 令牌桶限流 + 随机抖动
- 登录 / 发布等动作的账号级互斥
- 识别风控信号后熔断，指数退避冷却，并通知监听者（持久化、推送）
"""

import asyncio
import random
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from enum import StrEnum
from typing import TypeVar

from loguru import logger

from app.core.config import get_settings
from app.goofish.errors import RateLimitedError, RiskBlockedError, RiskControlError, SessionExpiredError
from app.goofish.guard.limiter import MemoryRateLimiter, RateLimiter
from app.goofish.guard.policy import Action, policies

T = TypeVar("T")
ANON = "anon"


class AccountState(StrEnum):
    ACTIVE = "active"
    NEED_LOGIN = "need_login"
    COOLDOWN = "cooldown"
    CIRCUIT_OPEN = "circuit_open"  # 触发风控，等待人工处理
    DISABLED = "disabled"


@dataclass
class Runtime:
    state: AccountState = AccountState.ACTIVE
    cooldown_until: float = 0.0  # time.time()
    strikes: int = 0
    successes: int = 0
    failures: int = 0
    last_error: str | None = None
    punish_url: str | None = None
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @property
    def health(self) -> int:
        score = 100 - self.strikes * 25 - min(self.failures, 10) * 3
        if self.state in (AccountState.CIRCUIT_OPEN, AccountState.NEED_LOGIN, AccountState.DISABLED):
            score = min(score, 20)
        elif self.state == AccountState.COOLDOWN:
            score = min(score, 50)
        return max(0, min(100, score))


StateListener = Callable[[str, Runtime, str], Awaitable[None]]


class RiskGuard:
    def __init__(self, limiter: RateLimiter | None = None, *, jitter: bool = True) -> None:
        self.limiter = limiter or MemoryRateLimiter()
        self.jitter = jitter
        self._rt: dict[str, Runtime] = defaultdict(Runtime)
        self._listeners: list[StateListener] = []

    # ------------------------------------------------------------ 状态管理
    def runtime(self, key: str) -> Runtime:
        return self._rt[key]

    def on_state_change(self, listener: StateListener) -> None:
        self._listeners.append(listener)

    async def _notify(self, key: str, reason: str) -> None:
        for listener in self._listeners:
            try:
                await listener(key, self._rt[key], reason)
            except Exception:  # noqa: BLE001
                logger.exception("风控状态监听器异常 key={}", key)

    def load(self, key: str, state: str, cooldown_until: float = 0.0, strikes: int = 0) -> None:
        rt = self._rt[key]
        rt.state = AccountState(state)
        rt.cooldown_until = cooldown_until
        rt.strikes = strikes
        if rt.state == AccountState.ACTIVE:
            rt.last_error = None
            rt.punish_url = None

    async def set_state(self, key: str, state: AccountState, reason: str = "") -> None:
        rt = self._rt[key]
        if rt.state == state:
            return
        rt.state = state
        if state == AccountState.ACTIVE:
            rt.punish_url = None
            rt.cooldown_until = 0
        await self._notify(key, reason or f"state->{state}")

    async def trip(self, key: str, reason: str, punish_url: str | None = None) -> None:
        """触发保护：有验证链接进入 CIRCUIT_OPEN 等待人工；无验证链接进入 COOLDOWN 短期避险。"""
        s = get_settings()
        rt = self._rt[key]
        rt.strikes += 1
        rt.last_error = reason
        rt.punish_url = punish_url
        if punish_url:
            # 真实平台安全惩罚 / 滑块验证：进入 CIRCUIT_OPEN，需要人工到闲鱼网页完成验证
            cooldown = min(s.guard_cooldown_base_seconds * 2 ** (rt.strikes - 1), s.guard_cooldown_max_seconds)
            rt.cooldown_until = time.time() + cooldown
            rt.state = AccountState.CIRCUIT_OPEN
            logger.warning(
                "风控熔断（需人工验证）key={} strikes={} 冷却 {}s 原因={}", key, rt.strikes, cooldown, reason
            )
        else:
            # 接口限流 / 挤爆报错：无滑块，进入短暂保护期，倒计时结束后自动自愈，不锁死全局业务
            cooldown = min(120 * 2 ** (rt.strikes - 1), 600)
            rt.cooldown_until = time.time() + cooldown
            rt.state = AccountState.COOLDOWN
            logger.warning(
                "风控限流避险（自动冷却）key={} strikes={} 冷却 {}s 原因={}", key, rt.strikes, cooldown, reason
            )
        await self._notify(key, reason)

    async def resolve(self, key: str) -> None:
        """人工完成验证后调用：进入冷却期，冷却结束后自动恢复。"""
        rt = self._rt[key]
        if rt.state == AccountState.CIRCUIT_OPEN:
            rt.state = AccountState.COOLDOWN
            rt.cooldown_until = max(rt.cooldown_until, time.time() + 60)
            await self._notify(key, "人工已处理，进入冷却")

    def _check(self, key: str, requires_login: bool) -> None:
        rt = self._rt[key]
        now = time.time()
        if rt.state == AccountState.DISABLED:
            raise RiskBlockedError("账号已停用", state=rt.state)
        if rt.state == AccountState.NEED_LOGIN and requires_login:
            raise RiskBlockedError("账号需要重新登录", state=rt.state)
        if rt.state in (AccountState.CIRCUIT_OPEN, AccountState.COOLDOWN):
            # 匿名通道没有账号可以去完成滑块验证：熔断也只等冷却结束，到点自动探活；
            # 账号通道的熔断仍需人工在闲鱼完成验证后解除
            manual = rt.state == AccountState.CIRCUIT_OPEN and key != ANON
            if manual or now < rt.cooldown_until:
                raise RiskBlockedError(
                    "账号被平台限制或处于暂停保护期，暂不执行操作",
                    state=rt.state,
                    retry_after=max(0.0, rt.cooldown_until - now),
                )

    # ------------------------------------------------------------ 执行
    async def run(self, key: str, action: Action, fn: Callable[[], Awaitable[T]]) -> T:
        policy = policies()[action]
        self._check(key, policy.requires_login and key != ANON)
        rt = self._rt[key]
        if rt.state == AccountState.COOLDOWN or (key == ANON and rt.state == AccountState.CIRCUIT_OPEN):
            rt.state = AccountState.ACTIVE  # 冷却结束：本次调用作为探活

        wait = await self.limiter.reserve(f"{key}:{action}", policy.rate, policy.per, policy.burst)
        if wait > policy.max_wait:
            raise RiskBlockedError(f"{action} 操作过于频繁", state="rate_limited", retry_after=wait)
        if wait > 0:
            await asyncio.sleep(wait)
        if self.jitter:
            s = get_settings()
            if s.guard_jitter_ms_max > 0:
                await asyncio.sleep(random.uniform(s.guard_jitter_ms_min, s.guard_jitter_ms_max) / 1000)

        if policy.exclusive:
            async with rt.lock:
                return await self._invoke(key, fn)
        return await self._invoke(key, fn)

    async def _invoke(self, key: str, fn: Callable[[], Awaitable[T]]) -> T:
        rt = self._rt[key]
        try:
            result = await fn()
        except RiskControlError as e:
            rt.failures += 1
            await self.trip(key, str(e), e.punish_url)
            raise
        except SessionExpiredError as e:
            rt.failures += 1
            rt.last_error = str(e)
            await self.set_state(key, AccountState.NEED_LOGIN, "登录态失效")
            raise
        except RateLimitedError as e:
            rt.failures += 1
            rt.state = AccountState.COOLDOWN
            rt.cooldown_until = time.time() + 300
            await self._notify(key, f"平台限流：{e}")
            raise
        rt.successes += 1
        if rt.failures:
            rt.failures -= 1
        return result
