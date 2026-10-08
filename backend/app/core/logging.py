"""日志：loguru 统一输出，并对敏感字段打码。"""

import re
import sys

from loguru import logger

_SENSITIVE = re.compile(
    r"(?P<key>cookie2|_m_h5_tk(?:_enc)?|unb|sgcookie|x5sec|accessToken|token|password|cookie)"
    r"(?P<sep>[\"']?\s*[:=]\s*[\"']?)(?P<val>[^;\"'&\s,}]+)",
    re.IGNORECASE,
)


def mask_secrets(text: str) -> str:
    def _sub(m: re.Match[str]) -> str:
        val = m.group("val")
        keep = val[:3] if len(val) > 8 else ""
        return f"{m.group('key')}{m.group('sep')}{keep}***"

    return _SENSITIVE.sub(_sub, text)


def _patch(record):  # type: ignore[no-untyped-def]
    record["message"] = mask_secrets(record["message"])


def setup_logging(level: str = "INFO") -> None:
    logger.remove()
    logger.configure(patcher=_patch)
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}</cyan> - <level>{message}</level>",
    )
