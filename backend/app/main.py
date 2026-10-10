"""FastAPI 应用入口。"""

from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app import bootstrap
from app.api.router import api_router
from app.core.config import DEV_SECRET, get_settings
from app.core.db import dispose_engine, init_engine, run_migrations, session_factory
from app.core.events import bus
from app.core.logging import setup_logging
from app.domains.message.router import ws_router
from app.domains.system import llm as llm_service
from app.domains.system.service import ensure_admin
from app.notify import service as notify_service
from app.runtime import get_runtime_or_none


@asynccontextmanager
async def lifespan(app: FastAPI):
    setup_logging()
    settings = get_settings()
    if settings.is_production and (settings.app_secret_key == DEV_SECRET or len(settings.app_secret_key) < 32):
        raise RuntimeError("生产环境必须设置至少 32 位的 APP_SECRET_KEY")
    if settings.is_production and "*" in settings.cors_origins:
        # 允许携带凭据的同时允许任意来源，等于任何网站都能以登录用户身份调用接口
        raise RuntimeError("生产环境的 CORS_ORIGINS 不能包含 *，请填写管理台的实际访问地址")
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
    await notify_service.drain()
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
        """存活检查：进程在就返回 ok。"""
        return {"status": "ok"}

    @app.get("/readyz", tags=["system"])
    async def readyz(response: Response) -> dict[str, Any]:
        """就绪检查：数据库（以及配置了的 Redis）可用才返回 200，供编排与反向代理判断能否接流量。"""
        checks: dict[str, str] = {}
        try:
            async with session_factory()() as s:
                await s.execute(text("SELECT 1"))
            checks["database"] = "ok"
        except Exception as e:  # noqa: BLE001
            checks["database"] = f"error: {type(e).__name__}"
        rt = get_runtime_or_none()
        if rt is not None and rt.redis is not None:
            try:
                await rt.redis.ping()
                checks["redis"] = "ok"
            except Exception as e:  # noqa: BLE001
                checks["redis"] = f"error: {type(e).__name__}"
        ready = all(v == "ok" for v in checks.values())
        if not ready:
            response.status_code = 503
        return {"status": "ok" if ready else "unavailable", "checks": checks}

    return app


app = create_app()
