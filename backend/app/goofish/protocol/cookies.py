"""Cookie 工具：解析、合并 Set-Cookie、登录态判断。"""

from collections.abc import Iterable

LOGIN_REQUIRED_COOKIES = ("unb", "cookie2", "_m_h5_tk")


def parse_cookie_str(raw: str) -> dict[str, str]:
    """解析 `a=1; b=2` 形式的 Cookie 字符串，同名以后出现的为准。"""
    cookies: dict[str, str] = {}
    for part in raw.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        name, _, value = part.partition("=")
        name = name.strip()
        if name:
            cookies[name] = value.strip()
    return cookies


def dump_cookie_str(cookies: dict[str, str]) -> str:
    return "; ".join(f"{k}={v}" for k, v in cookies.items())


def parse_set_cookie(headers: Iterable[str]) -> dict[str, str]:
    """从 Set-Cookie 头中提取 name=value（忽略 Path/Domain/Expires 等属性）。"""
    result: dict[str, str] = {}
    for header in headers:
        first = header.split(";", 1)[0].strip()
        if "=" not in first:
            continue
        name, _, value = first.partition("=")
        name = name.strip()
        if not name:
            continue
        # 服务端用空值 + 过期时间删除 cookie
        if value == "" and "expires=thu, 01-jan-1970" in header.lower():
            result[name] = ""
        else:
            result[name] = value
    return result


def merge_cookies(base: dict[str, str], updates: dict[str, str]) -> bool:
    """原地合并，返回是否有变化。值为空字符串表示删除。"""
    changed = False
    for name, value in updates.items():
        if value == "":
            if name in base:
                base.pop(name)
                changed = True
        elif base.get(name) != value:
            base[name] = value
            changed = True
    return changed


def h5_token(cookies: dict[str, str]) -> str:
    """签名用 token：_m_h5_tk 下划线之前的部分。"""
    tk = cookies.get("_m_h5_tk", "")
    return tk.split("_", 1)[0] if tk else ""


def is_logged_in(cookies: dict[str, str]) -> bool:
    return all(cookies.get(k) for k in LOGIN_REQUIRED_COOKIES)


def user_id(cookies: dict[str, str]) -> str | None:
    return cookies.get("unb") or None
