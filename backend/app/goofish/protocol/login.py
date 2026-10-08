"""扫码登录（passport.goofish.com）与登录态续期。

需要人脸 / 短信核身时，返回 NEED_VERIFY 与核身链接，由人工在浏览器中完成，不做自动处理。
"""

import random
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import httpx

from app.goofish.protocol.cookies import dump_cookie_str, is_logged_in, merge_cookies, parse_set_cookie
from app.goofish.protocol.mtop import DEFAULT_UA, MtopClient
from app.goofish.protocol.sign import gen_cna

PASSPORT = "https://passport.goofish.com"
_BIZ_PARAMS = f"taobaoBizLoginFrom=web&renderRefer={quote('https://www.goofish.com/')}"


class QrStatus(StrEnum):
    NEW = "NEW"
    SCANED = "SCANED"
    CONFIRMED = "CONFIRMED"
    EXPIRED = "EXPIRED"
    CANCELED = "CANCELED"
    NEED_VERIFY = "NEED_VERIFY"
    SUCCESS = "SUCCESS"
    ERROR = "ERROR"


@dataclass
class QrSession:
    qr_content: str
    t: str
    ck: str
    csrf_token: str
    cookies: dict[str, str] = field(default_factory=dict)


@dataclass
class QrPollResult:
    status: QrStatus
    cookies: dict[str, str] = field(default_factory=dict)
    verify_url: str | None = None
    message: str = ""


class QrLoginClient:
    def __init__(self, *, proxy: str | None = None, transport: httpx.AsyncBaseTransport | None = None) -> None:
        self._proxy = proxy
        self._transport = transport
        self._http = httpx.AsyncClient(
            proxy=proxy,
            transport=transport,
            timeout=15,
            follow_redirects=False,
            headers={"User-Agent": DEFAULT_UA, "Accept-Language": "zh-CN,zh;q=0.9"},
        )

    async def aclose(self) -> None:
        await self._http.aclose()

    def _common(self, sess: QrSession) -> dict[str, str]:
        return {
            "appName": "xianyu",
            "fromSite": "77",
            "appEntrance": "web",
            "_csrf_token": sess.csrf_token,
            "umidToken": "",
            "hsiz": sess.cookies.get("cookie2", ""),
            "bizParams": _BIZ_PARAMS,
            "mainPage": "false",
            "isMobile": "false",
            "lang": "zh_CN",
            "returnUrl": "",
            "umidTag": "SERVER",
        }

    async def _get(self, sess: QrSession, url: str, **kw: Any) -> httpx.Response:
        resp = await self._http.get(url, headers=self._headers(sess, kw.pop("headers", None)), **kw)
        merge_cookies(sess.cookies, parse_set_cookie(resp.headers.get_list("set-cookie")))
        return resp

    async def _post(self, sess: QrSession, url: str, **kw: Any) -> httpx.Response:
        resp = await self._http.post(url, headers=self._headers(sess, kw.pop("headers", None)), **kw)
        merge_cookies(sess.cookies, parse_set_cookie(resp.headers.get_list("set-cookie")))
        return resp

    @staticmethod
    def _headers(sess: QrSession, extra: dict[str, str] | None) -> dict[str, str]:
        h = {
            "Cookie": dump_cookie_str(sess.cookies),
            "Referer": f"{PASSPORT}/mini_login.htm",
            "Origin": PASSPORT,
        }
        h.update(extra or {})
        return h

    async def start(self) -> QrSession:
        sess = QrSession(qr_content="", t="", ck="", csrf_token="", cookies={"cna": gen_cna()})
        await self._get(
            sess,
            f"{PASSPORT}/mini_login.htm",
            params={
                "lang": "zh_cn",
                "appName": "xianyu",
                "appEntrance": "web",
                "styleType": "vertical",
                "bizParams": "",
                "notLoadSsoView": "false",
                "notKeepLogin": "false",
                "isMobile": "false",
                "qrCodeFirst": "false",
                "stie": "77",
                "rnd": str(random.random()),
            },
            headers={"Referer": "https://www.goofish.com/"},
        )
        sess.csrf_token = sess.cookies.get("XSRF-TOKEN", "")
        resp = await self._get(sess, f"{PASSPORT}/newlogin/qrcode/generate.do", params=self._common(sess))
        data = (resp.json().get("content") or {}).get("data") or {}
        if not data.get("codeContent"):
            raise RuntimeError(f"生成二维码失败：{resp.text[:200]}")
        sess.qr_content, sess.t, sess.ck = data["codeContent"], str(data["t"]), data["ck"]
        return sess

    async def poll(self, sess: QrSession) -> QrPollResult:
        body = {
            **self._common(sess),
            "navlanguage": "zh-CN",
            "navUserAgent": DEFAULT_UA,
            "navPlatform": "MacIntel",
            "isIframe": "true",
            "documentReferer": "https://www.goofish.com/",
            "defaultView": "qrcode",
            "deviceId": sess.cookies.get("cna", ""),
            "t": sess.t,
            "ck": sess.ck,
        }
        resp = await self._post(
            sess,
            f"{PASSPORT}/newlogin/qrcode/query.do",
            params={"appName": "xianyu", "fromSite": "77"},
            data=body,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        data = (resp.json().get("content") or {}).get("data") or {}
        status = str(data.get("qrCodeStatus") or "")
        if data.get("iframeRedirect") or data.get("iframeRedirectUrl"):
            return QrPollResult(QrStatus.NEED_VERIFY, verify_url=data.get("iframeRedirectUrl"), message="需要身份验证")
        if status == "CONFIRMED":
            token = data.get("token") or data.get("lgToken")
            if token:
                await self._post(
                    sess,
                    f"{PASSPORT}/login_token/login.do",
                    params={
                        "token": token,
                        "subFlow": "DIALOG_CHECK_LOGIN_RPC",
                        "nextCode": "0018",
                        "bizScene": "qrcode",
                        "confirm": "true",
                    },
                    data={"deviceId": sess.cookies.get("cna", "")},
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                )
            # 登录后刷新 _m_h5_tk
            sess.cookies.pop("_m_h5_tk", None)
            sess.cookies.pop("_m_h5_tk_enc", None)
            async with MtopClient(sess.cookies, proxy=self._proxy, transport=self._transport) as mtop:
                try:
                    await mtop.ensure_token()
                except Exception:  # noqa: BLE001
                    pass
                sess.cookies = mtop.cookies
            if is_logged_in(sess.cookies):
                return QrPollResult(QrStatus.SUCCESS, cookies=dict(sess.cookies))
            return QrPollResult(QrStatus.ERROR, message="已确认但未拿到完整登录 Cookie")
        try:
            return QrPollResult(QrStatus(status))
        except ValueError:
            return QrPollResult(QrStatus.ERROR, message=f"未知状态 {status}")


async def has_login_renew(cookies: dict[str, str], *, proxy: str | None = None) -> bool:
    """调用 passport hasLogin.do 尝试续期登录态，成功时原地更新 cookies。"""
    async with httpx.AsyncClient(proxy=proxy, timeout=15, headers={"User-Agent": DEFAULT_UA}) as http:
        resp = await http.post(
            f"{PASSPORT}/newlogin/hasLogin.do",
            params={"appName": "xianyu", "fromSite": "77"},
            data={"hid": cookies.get("unb", ""), "ltl": "true", "appName": "xianyu", "appEntrance": "web"},
            headers={
                "Cookie": dump_cookie_str(cookies),
                "Referer": f"{PASSPORT}/mini_login.htm",
                "Origin": PASSPORT,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        merge_cookies(cookies, parse_set_cookie(resp.headers.get_list("set-cookie")))
        try:
            return bool((resp.json().get("content") or {}).get("success"))
        except ValueError:
            return False
