from fastapi import APIRouter

from app.domains.system.router import router as system_router
from app.notify.router import router as notify_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system_router)
api_router.include_router(notify_router)
