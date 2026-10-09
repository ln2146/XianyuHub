"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app import bootstrap
from app.api.router import api_router
from app.core.config import DEV_SECRET, get_settings
from app.core.db import dispose_engine, init_engine, run_migrations
from app.core.events import bus
from app.core.logging import setup_logging
from app.domains.message.router import ws_router
from app.domains.system import llm as llm_service
from app.domains.system.service import ensure_admin


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    if settings.is_production and (settings.app_secret_key == DEV_SECRET or len(settings.app_secret_key) < 32):
        raise RuntimeError("生产环境必须设置至少 32 位的 APP_SECRET_KEY")
    init_engine()
    await run_migrations()
    await ensure_admin()
    await llm_service.seed_from_env()
    await bootstrap.setup_runtime()
    if bootstrap.workers_enabled():
        await bootstrap.start_workers()
    yield
    await bus.drain()
    await bootstrap.shutdown()
    await dispose_engine()


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Total-Count"],
    )
    app.include_router(api_router)
    app.include_router(ws_router)

    @app.get("/healthz", tags=["system"])
    async def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
