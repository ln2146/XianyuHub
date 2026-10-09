"""密码哈希与 JWT。"""

import ipaddress
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

import bcrypt
import jwt
from fastapi import Request

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


def create_access_token(subject: str | int, role: str, expires_minutes: int | None = None) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {"sub": str(subject), "role": role, "exp": expire}
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().app_secret_key, algorithms=[ALGORITHM])


# ---------------------------------------------------------------- 本机免登录
_LOCAL_NAMES = {"localhost", "127.0.0.1", "::1"}
_PROXY_HEADERS = ("x-forwarded-for", "x-real-ip", "forwarded", "x-forwarded-host")


def _hostname(netloc: str) -> str:
    """'127.0.0.1:8000' / '[::1]:8000' / 'localhost' → 主机名（小写、去端口与方括号）。"""
    return (urlsplit(f"//{netloc}").hostname or "").lower()


def is_local_request(request: Request) -> bool:
    """请求是否“本机浏览器直接访问本机服务”。

    - 来源 IP 必须是回环地址：局域网 / 公网访问不算；
    - 不能带反向代理头：经 Caddy / Nginx 转发的一律不算（即使代理在本机）；
    - Host 必须是本机名：防 DNS 重绑定（恶意域名解析到 127.0.0.1）；
    - 若有 Origin，也必须是本机页面：防其他网站在浏览器里跨站调用。
    """
    try:
        if not request.client or not ipaddress.ip_address(request.client.host).is_loopback:
            return False
    except ValueError:
        return False
    if any(request.headers.get(h) for h in _PROXY_HEADERS):
        return False
    if _hostname(request.headers.get("host", "")) not in _LOCAL_NAMES:
        return False
    origin = request.headers.get("origin")
    if origin and (urlsplit(origin).hostname or "").lower() not in _LOCAL_NAMES:
        return False
    return True
