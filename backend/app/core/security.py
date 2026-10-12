"""密码哈希与 JWT。"""

from datetime import UTC, datetime, timedelta

import bcrypt
import jwt

from app.core.config import get_settings

ALGORITHM = "HS256"


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("ascii"))
    except ValueError:
        return False


# 浏览器扩展自动续期用的令牌：只能调用「同步登录态」接口，不能当作登录令牌访问其他接口
COOKIE_SYNC_SCOPE = "cookie_sync"


def create_access_token(
    subject: str | int, role: str, expires_minutes: int | None = None, *, scope: str | None = None
) -> str:
    settings = get_settings()
    expire = datetime.now(UTC) + timedelta(minutes=expires_minutes or settings.access_token_expire_minutes)
    payload = {"sub": str(subject), "role": role, "exp": expire}
    if scope:
        payload["scope"] = scope
    return jwt.encode(payload, settings.app_secret_key, algorithm=ALGORITHM)


def decode_access_token(token: str) -> dict:
    return jwt.decode(token, get_settings().app_secret_key, algorithms=[ALGORITHM])


def user_id_from_token(token: str, *, scope: str | None = None) -> int:
    """解析令牌里的用户 ID；签名有效但内容异常（缺 sub、非整数等）也按无效令牌处理，返回 401 而不是 500。
    scope 必须与令牌的用途一致：普通接口不接受专用令牌，专用接口也不接受普通登录令牌。"""
    payload = decode_access_token(token)
    if payload.get("scope") != scope:
        raise jwt.InvalidTokenError("令牌用途不符")
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError, OverflowError) as e:
        raise jwt.InvalidTokenError("令牌内容无效") from e
    if not 0 < user_id < 2**63:  # 超出数据库整数范围会在查询时报错
        raise jwt.InvalidTokenError("令牌内容无效")
    return user_id
