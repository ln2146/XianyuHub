"""SessionStore 的数据库实现：Cookie / 代理加密存取。"""

import json

from sqlalchemy import select

from app.core.crypto import get_vault
from app.core.db import session_factory
from app.domains.account.models import XyAccount, XyAccountCredential


class DbSessionStore:
    async def load_cookies(self, account_id: int) -> dict[str, str]:
        async with session_factory()() as s:
            cred = (
                await s.execute(select(XyAccountCredential).where(XyAccountCredential.account_id == account_id))
            ).scalar_one_or_none()
            if cred is None:
                return {}
            return json.loads(get_vault().decrypt(cred.cookie_enc) or "{}")

    async def save_cookies(self, account_id: int, cookies: dict[str, str]) -> None:
        enc = get_vault().encrypt(json.dumps(cookies, ensure_ascii=False))
        async with session_factory()() as s:
            cred = (
                await s.execute(select(XyAccountCredential).where(XyAccountCredential.account_id == account_id))
            ).scalar_one_or_none()
            if cred is None:
                s.add(XyAccountCredential(account_id=account_id, cookie_enc=enc))
            else:
                cred.cookie_enc = enc
            await s.commit()

    async def get_proxy(self, account_id: int) -> str | None:
        async with session_factory()() as s:
            acc = await s.get(XyAccount, account_id)
            if acc is None or not acc.proxy_enc:
                return None
            return get_vault().decrypt(acc.proxy_enc)
