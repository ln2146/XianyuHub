from fastapi import APIRouter

from app.domains.account.router import router as account_router
from app.domains.buyer.router import router as buyer_router
from app.domains.goods.router import router as goods_router
from app.domains.message.router import router as message_router
from app.domains.order.router import router as order_router
from app.domains.system.router import router as system_router
from app.notify.router import router as notify_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(system_router)
api_router.include_router(notify_router)
api_router.include_router(account_router)
api_router.include_router(buyer_router)
api_router.include_router(goods_router)
api_router.include_router(message_router)
api_router.include_router(order_router)
