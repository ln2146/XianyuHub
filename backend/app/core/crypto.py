"""凭证加密：AES-256-GCM。Cookie、密码、卡密等敏感数据落库前必须经过 Vault。"""

import base64
import hashlib
import os
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from loguru import logger

from app.core.config import get_settings

_VERSION = b"v1"


class Vault:
    def __init__(self, key: bytes) -> None:
        if len(key) != 32:
            raise ValueError("CREDENTIAL_MASTER_KEY 必须是 32 字节（base64 编码）")
        self._aes = AESGCM(key)

    def encrypt(self, plaintext: str | None) -> str | None:
        if plaintext is None:
            return None
        nonce = os.urandom(12)
        ct = self._aes.encrypt(nonce, plaintext.encode("utf-8"), _VERSION)
        return base64.b64encode(_VERSION + nonce + ct).decode("ascii")

    def decrypt(self, token: str | None) -> str | None:
        if token is None:
            return None
        raw = base64.b64decode(token)
        if raw[:2] != _VERSION:
            raise ValueError("未知的密文版本")
        nonce, ct = raw[2:14], raw[14:]
        return self._aes.decrypt(nonce, ct, _VERSION).decode("utf-8")


@lru_cache
def get_vault() -> Vault:
    settings = get_settings()
    if settings.credential_master_key:
        return Vault(base64.b64decode(settings.credential_master_key))
    if settings.is_production:
        raise RuntimeError("生产环境必须配置 CREDENTIAL_MASTER_KEY")
    logger.warning("未配置 CREDENTIAL_MASTER_KEY，开发环境使用由 APP_SECRET_KEY 派生的密钥")
    return Vault(hashlib.sha256(("vault:" + settings.app_secret_key).encode()).digest())
