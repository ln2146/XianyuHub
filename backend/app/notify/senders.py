"""各通知渠道的发送实现。每个 sender 接收统一的 Notification，自行转换为渠道格式。"""

import asyncio
import re
import smtplib
from email.mime.text import MIMEText
from typing import Any

import httpx
from pydantic import BaseModel


class Notification(BaseModel):
    event: str
    title: str
    content: str
    url: str | None = None
    image_url: str | None = None


class SendError(Exception):
    pass


def _markdown(n: Notification) -> str:
    parts = [f"**{n.title}**", "", n.content]
    if n.image_url:
        parts += ["", f"![]({n.image_url})"]
    if n.url:
        parts += ["", f"[查看详情]({n.url})"]
    return "\n".join(parts)


def _plain(n: Notification) -> str:
    return "\n".join(p for p in [n.title, n.content, n.url or ""] if p)


async def _post(http: httpx.AsyncClient, url: str, **kw: Any) -> httpx.Response:
    resp = await http.post(url, **kw)
    if resp.status_code >= 400:
        raise SendError(f"HTTP {resp.status_code}: {resp.text[:200]}")
    return resp


async def send_wecom(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    resp = await _post(http, cfg["webhook_url"], json={"msgtype": "markdown", "markdown": {"content": _markdown(n)}})
    if resp.json().get("errcode", 0) != 0:
        raise SendError(resp.text[:200])


async def send_feishu(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    card = {
        "msg_type": "interactive",
        "card": {
            "header": {"title": {"tag": "plain_text", "content": n.title}},
            "elements": [{"tag": "markdown", "content": n.content + (f"\n[查看详情]({n.url})" if n.url else "")}],
        },
    }
    resp = await _post(http, cfg["webhook_url"], json=card)
    if resp.json().get("code", 0) != 0:
        raise SendError(resp.text[:200])


_SC3_UID = re.compile(r"^sctp(\d+)t")


async def send_serverchan(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    """Server酱（推送到个人微信）：Turbo 版 SCT… 与 Server酱³ sctp… 两种 SendKey 都支持。"""
    key = cfg["sendkey"].strip()
    m = _SC3_UID.match(key)
    url = f"https://{m.group(1)}.push.ft07.com/send/{key}.send" if m else f"https://sctapi.ftqq.com/{key}.send"
    resp = await _post(http, url, json={"title": n.title[:100], "desp": _markdown(n)})
    if resp.json().get("code", 0) != 0:
        raise SendError(resp.text[:200])


async def send_pushplus(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    """PushPlus 推送加（关注公众号即可推送到个人微信）。"""
    resp = await _post(
        http,
        "https://www.pushplus.plus/send",
        json={"token": cfg["token"], "title": n.title[:100], "content": _markdown(n), "template": "markdown"},
    )
    if resp.json().get("code") != 200:
        raise SendError(resp.text[:200])


async def send_dingtalk(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    resp = await _post(
        http, cfg["webhook_url"], json={"msgtype": "markdown", "markdown": {"title": n.title, "text": _markdown(n)}}
    )
    if resp.json().get("errcode", 0) != 0:
        raise SendError(resp.text[:200])


async def send_telegram(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    base = cfg.get("api_base", "https://api.telegram.org")
    await _post(
        http,
        f"{base}/bot{cfg['bot_token']}/sendMessage",
        json={"chat_id": cfg["chat_id"], "text": _plain(n), "disable_web_page_preview": False},
    )


async def send_bark(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    body: dict[str, Any] = {"title": n.title, "body": n.content, "group": "XianyuHub"}
    if n.url:
        body["url"] = n.url
    if n.image_url:
        body["icon"] = n.image_url
    await _post(http, cfg["server_url"].rstrip("/") + "/" + cfg["device_key"], json=body)


async def send_ntfy(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    headers = {"Title": n.title.encode("utf-8").decode("latin-1"), "Tags": "fish"}
    if n.url:
        headers["Click"] = n.url
    if n.image_url:
        headers["Attach"] = n.image_url
    if cfg.get("token"):
        headers["Authorization"] = f"Bearer {cfg['token']}"
    await _post(
        http,
        cfg.get("server_url", "https://ntfy.sh").rstrip("/") + "/" + cfg["topic"],
        content=n.content.encode(),
        headers=headers,
    )


async def send_webhook(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    headers = dict(cfg.get("headers") or {})
    await _post(http, cfg["url"], json=n.model_dump(), headers=headers)


async def send_email(http: httpx.AsyncClient, cfg: dict, n: Notification) -> None:
    def _send() -> None:
        msg = MIMEText(_plain(n), "plain", "utf-8")
        msg["Subject"] = n.title
        msg["From"] = cfg["username"]
        msg["To"] = cfg["to"]
        cls = smtplib.SMTP_SSL if cfg.get("ssl", True) else smtplib.SMTP
        with cls(cfg["host"], int(cfg.get("port", 465)), timeout=15) as smtp:
            smtp.login(cfg["username"], cfg["password"])
            smtp.send_message(msg)

    await asyncio.to_thread(_send)


SENDERS = {
    "serverchan": (send_serverchan, ["sendkey"]),
    "pushplus": (send_pushplus, ["token"]),
    "wecom": (send_wecom, ["webhook_url"]),
    "feishu": (send_feishu, ["webhook_url"]),
    "dingtalk": (send_dingtalk, ["webhook_url"]),
    "telegram": (send_telegram, ["bot_token", "chat_id"]),
    "bark": (send_bark, ["server_url", "device_key"]),
    "ntfy": (send_ntfy, ["topic"]),
    "webhook": (send_webhook, ["url"]),
    "email": (send_email, ["host", "username", "password", "to"]),
}


# 可选配置项及默认值（供管理台渲染表单）
OPTIONAL_FIELDS: dict[str, dict[str, object]] = {
    "telegram": {"api_base": "https://api.telegram.org"},
    "ntfy": {"server_url": "https://ntfy.sh", "token": ""},
    "webhook": {"headers": {}},
    "email": {"port": 465, "ssl": True},
}


def validate_config(channel_type: str, cfg: dict) -> None:
    if channel_type not in SENDERS:
        raise ValueError(f"不支持的通知渠道：{channel_type}")
    missing = [k for k in SENDERS[channel_type][1] if not cfg.get(k)]
    if missing:
        raise ValueError(f"缺少配置项：{', '.join(missing)}")
