import httpx
import pytest

from app.core.config import get_settings
from app.core.crypto import get_vault
from app.core.events import bus
from app.intelligence.llm import set_llm

ADMIN_PASSWORD = "admin-pass-123"


@pytest.fixture(autouse=True)
def _env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path / "data"))
    monkeypatch.setenv("DATABASE_URL", f"sqlite+aiosqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("ADMIN_USERNAME", "admin")
    monkeypatch.setenv("ADMIN_PASSWORD", ADMIN_PASSWORD)
    monkeypatch.setenv("APP_SECRET_KEY", "test-secret-key-0123456789abcdef-xyz")
    monkeypatch.setenv("RUN_WORKERS_IN_API", "false")
    monkeypatch.setenv("REDIS_URL", "")
    monkeypatch.setenv("GUARD_JITTER_MS_MAX", "0")
    monkeypatch.setenv("GUARD_RATE_MULTIPLIER", "100")
    monkeypatch.setenv("GUARD_JITTER_MS_MIN", "0")
    get_settings.cache_clear()
    get_vault.cache_clear()
    bus.clear()
    set_llm(None)
    yield
    set_llm(None)
    get_settings.cache_clear()
    get_vault.cache_clear()
    bus.clear()


@pytest.fixture
async def app():
    from app.main import create_app

    application = create_app()
    async with application.router.lifespan_context(application):
        yield application


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def admin_client(client):
    resp = await client.post("/api/v1/auth/login", json={"username": "admin", "password": ADMIN_PASSWORD})
    assert resp.status_code == 200, resp.text
    client.headers["Authorization"] = f"Bearer {resp.json()['access_token']}"
    return client
