"""mtop H5 网关客户端。

- 自动签名；响应的 Set-Cookie 会合并回 cookie（_m_h5_tk 刷新）
- TOKEN 过期自动重签重试
- 统一把返回码映射为 app.goofish.errors 中的异常类型
"""

import json
from collections.abc import Awaitable, Callable
from typing import Any

import httpx
from loguru import logger

from app.goofish.errors import (
    BizError,
    NetworkError,
    RateLimitedError,
    RiskControlError,
    SessionExpiredError,
    TokenExpiredError,
)
from app.goofish.protocol.cookies import dump_cookie_str, h5_token, merge_cookies, parse_set_cookie
from app.goofish.protocol.sign import MTOP_APP_KEY, gen_cna, mtop_sign, now_ms

MTOP_BASE = "https://h5api.m.goofish.com/h5/{api}/{version}/"
DEFAULT_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"
)
# 用于匿名获取 _m_h5_tk 的轻量接口
TOKEN_BOOTSTRAP_API = "mtop.gaia.nodejs.gaia.idle.data.gw.v2.index.get"

_TOKEN_CODES = ("FAIL_SYS_TOKEN_EXOIRED", "FAIL_SYS_TOKEN_EXPIRED", "FAIL_SYS_TOKEN_EMPTY", "FAIL_SYS_ILLEGAL_ACCESS")
_SESSION_CODES = ("FAIL_SYS_SESSION_EXPIRED", "FAIL_SYS_LOGIN", "FAIL_SYS_USER_NOT_LOGIN")
_RISK_CODES = ("FAIL_SYS_USER_VALIDATE", "RGV587_ERROR", "FAIL_BIZ_WUA_IS_MACHINE")
_RISK_WORDS = ("挤爆", "punish", "x5secdata", "_____tmd_____", "baxia")
_RATE_CODES = ("FAIL_SYS_TRAFFIC_LIMIT", "FAIL_SYS_FLOWLIMIT")

CookieListener = Callable[[dict[str, str]], Awaitable[None] | None]


def classify_ret(ret: list[str], data: Any, api: str) -> None:
    """根据 ret 抛出对应异常；成功时直接返回。"""
    if any(str(r).startswith("SUCCESS") for r in ret):
        return
    text = " ".join(str(r) for r in ret)
    blob = text + (json.dumps(data, ensure_ascii=False) if isinstance(data, dict) else "")
    if any(code in text for code in _RISK_CODES) or any(w in blob for w in _RISK_WORDS):
        url = data.get("url") if isinstance(data, dict) else None
        raise RiskControlError(f"触发风控：{text}", punish_url=url, ret=ret, api=api)
    if any(code in text for code in _TOKEN_CODES):
        raise TokenExpiredError(text, ret=ret, api=api)
    if any(code in text for code in _SESSION_CODES):
        raise SessionExpiredError(text, ret=ret, api=api)
    if any(code in text for code in _RATE_CODES) or "频繁" in text:
        raise RateLimitedError(text, ret=ret, api=api)
    raise BizError(text or "未知错误", ret=ret, api=api)


class MtopClient:
    def __init__(
        self,
        cookies: dict[str, str] | None = None,
        *,
        proxy: str | None = None,
        user_agent: str = DEFAULT_UA,
        on_cookies_updated: CookieListener | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        timeout: float = 20.0,
    ) -> None:
        self.cookies: dict[str, str] = dict(cookies or {})
        if "cna" not in self.cookies:
            self.cookies["cna"] = gen_cna()
        self.user_agent = user_agent
        self._on_cookies_updated = on_cookies_updated
        self._http = httpx.AsyncClient(
            proxy=proxy,
            transport=transport,
            timeout=timeout,
            headers={
                "User-Agent": user_agent,
                "Accept": "application/json",
                "Accept-Language": "zh-CN,zh;q=0.9",
                "Origin": "https://www.goofish.com",
                "Referer": "https://www.goofish.com/",
            },
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    async def __aenter__(self) -> "MtopClient":
        return self

    async def __aexit__(self, *exc: object) -> None:
        await self.aclose()

    async def _absorb_cookies(self, response: httpx.Response) -> None:
        updates = parse_set_cookie(response.headers.get_list("set-cookie"))
        if updates and merge_cookies(self.cookies, updates) and self._on_cookies_updated:
            result = self._on_cookies_updated(dict(self.cookies))
            if result is not None:
                await result

    async def call(
        self,
        api: str,
        data: dict[str, Any] | None = None,
        *,
        version: str = "1.0",
        extra_params: dict[str, str] | None = None,
        token_retries: int = 2,
    ) -> dict[str, Any]:
        """调用 mtop 接口，返回响应中的 data 字段。"""
        body = json.dumps(data or {}, separators=(",", ":"), ensure_ascii=False)
        attempt = 0
        while True:
            t = now_ms()
            params = {
                "jsv": "2.7.2",
                "appKey": MTOP_APP_KEY,
                "t": str(t),
                "sign": mtop_sign(h5_token(self.cookies), t, body),
                "v": version,
                "type": "originaljson",
                "accountSite": "xianyu",
                "dataType": "json",
                "timeout": "20000",
                "api": api,
                "sessionOption": "AutoLoginOnly",
                **(extra_params or {}),
            }
            try:
                resp = await self._http.post(
                    MTOP_BASE.format(api=api, version=version),
                    params=params,
                    data={"data": body},
                    headers={"Cookie": dump_cookie_str(self.cookies)},
                )
            except httpx.HTTPError as e:
                raise NetworkError(f"请求失败：{e!r}", api=api) from e
            await self._absorb_cookies(resp)
            try:
                payload = resp.json()
            except ValueError as e:
                if any(w in resp.text for w in _RISK_WORDS) or "punish" in str(resp.url):
                    raise RiskControlError("被重定向到验证页", punish_url=str(resp.url), api=api) from e
                raise NetworkError(f"非 JSON 响应（HTTP {resp.status_code}）", api=api) from e

            ret = payload.get("ret") or []
            result = payload.get("data") or {}
            try:
                classify_ret(ret, result, api)
                return result
            except TokenExpiredError:
                attempt += 1
                if attempt > token_retries:
                    raise
                logger.debug("mtop token 过期，重签重试 api={} attempt={}", api, attempt)

    async def ensure_token(self) -> None:
        """匿名获取 _m_h5_tk（搜索等只读接口无需登录）。"""
        if h5_token(self.cookies):
            return
        try:
            await self.call(TOKEN_BOOTSTRAP_API, {}, token_retries=1)
        except (TokenExpiredError, BizError):
            # 只需要响应里的 Set-Cookie。该接口的业务参数随网页版变化（如 2026-10 起要求 piUrl），
            # 业务报错不影响拿到 _m_h5_tk；风控类错误仍然向上抛出
            pass
        if not h5_token(self.cookies):
            raise NetworkError("无法获取 _m_h5_tk", api=TOKEN_BOOTSTRAP_API)
