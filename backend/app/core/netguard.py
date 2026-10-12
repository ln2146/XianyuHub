"""出站请求的目标地址校验（防 SSRF）。

用户可以填写地址的出站请求（自定义发货接口、Webhook / Bark / ntfy 等通知渠道）都要先过这里：
- 云主机元数据、链路本地、组播等地址任何人都不能访问；
- 回环和内网地址只允许管理员使用（自部署时，管理员把通知或取货接口指向 NAS / 局域网服务是正常需求），
  普通成员不能借此探测或访问部署机所在的内网。

请求发出前按实际解析出的 IP 校验，且出站请求都不跟随重定向。
"""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.core.db import session_factory


class UnsafeTargetError(ValueError):
    pass


def _check_ip(ip: ipaddress.IPv4Address | ipaddress.IPv6Address, *, allow_private: bool) -> None:
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    if ip.is_link_local or ip.is_multicast or ip.is_unspecified:
        raise UnsafeTargetError(f"不允许访问该地址：{ip}")
    if not allow_private and (ip.is_private or ip.is_loopback or ip.is_reserved or not ip.is_global):
        raise UnsafeTargetError(f"不允许访问内网或本机地址：{ip}（仅管理员可以使用内网地址）")


async def check_host(host: str, *, allow_private: bool = False) -> None:
    if not host:
        raise UnsafeTargetError("地址缺少主机名")
    try:
        ips = [ipaddress.ip_address(host.strip("[]"))]
    except ValueError:
        if allow_private:
            return  # 管理员本就能访问部署机所在网络：只拦字面量的元数据 / 链路本地地址，不必解析域名
        try:
            infos = await asyncio.get_running_loop().getaddrinfo(host, None, type=socket.SOCK_STREAM)
        except OSError as e:
            raise UnsafeTargetError(f"无法解析主机名：{host}") from e
        ips = [ipaddress.ip_address(info[4][0].split("%")[0]) for info in infos]
    for ip in ips:
        _check_ip(ip, allow_private=allow_private)


async def check_url(url: str, *, allow_private: bool = False) -> None:
    parts = urlsplit(url or "")
    if parts.scheme not in ("http", "https"):
        raise UnsafeTargetError("地址必须以 http:// 或 https:// 开头")
    await check_host(parts.hostname or "", allow_private=allow_private)


async def owner_may_use_private(owner_id: int | None) -> bool:
    """配置归属于管理员时才允许内网地址。"""
    from app.domains.system.models import Role, User

    if owner_id is None:
        return False
    async with session_factory()() as s:
        user = await s.get(User, owner_id)
    return user is not None and user.role == Role.ADMIN
