"""上传与外部下载的资源限制：只读到上限为止，不把整份大文件先读进内存。"""

from typing import Annotated

from fastapi import UploadFile
from pydantic import StringConstraints

CHUNK = 1024 * 1024

# 本地上传图片的 ID（goods.service.save_upload 生成）：只认这个格式，防止引用任意路径
UploadId = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{32}\.(jpg|png|webp)$")]


class TooLarge(ValueError):
    pass


async def read_limited(file: UploadFile, max_bytes: int, message: str) -> bytes:
    """分块读取上传文件，超过 max_bytes 立即停止并报错。"""
    if file.size is not None and file.size > max_bytes:
        raise TooLarge(message)
    buf = bytearray()
    while chunk := await file.read(CHUNK):
        buf += chunk
        if len(buf) > max_bytes:
            raise TooLarge(message)
    return bytes(buf)


def sniff_image(data: bytes) -> str | None:
    """按文件头判断真实图片格式（不信任客户端或对方服务器声明的 Content-Type）。"""
    if data[:3] == b"\xff\xd8\xff":
        return "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "image/webp"
    return None
