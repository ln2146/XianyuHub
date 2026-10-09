"""日志：loguru 统一输出，并对敏感字段打码。"""

import logging
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


_TOKEN_QS = re.compile(r"(token=)[^&\s\"']+")


class _AccessTokenFilter(logging.Filter):
    """uvicorn 访问日志会记录完整 URL，其中 WebSocket 的 ?token= 是登录凭证，需要打码。"""

    def filter(self, record: logging.LogRecord) -> bool:
        if record.args:
            record.args = tuple(_TOKEN_QS.sub(r"\1***", a) if isinstance(a, str) else a for a in record.args)
        if isinstance(record.msg, str):
            record.msg = _TOKEN_QS.sub(r"\1***", record.msg)
        return True


def setup_logging(level: str = "INFO") -> None:
    for name in ("uvicorn.access", "uvicorn.error"):
        lg = logging.getLogger(name)
        if not any(isinstance(f, _AccessTokenFilter) for f in lg.filters):
            lg.addFilter(_AccessTokenFilter())
    logger.remove()
    logger.configure(patcher=_patch)
    logger.add(
        sys.stderr,
        level=level,
        format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <7}</level> | "
        "<cyan>{name}</cyan> - <level>{message}</level>",
    )
