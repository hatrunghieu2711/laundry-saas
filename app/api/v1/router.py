"""Router tổng hợp /api/v1. Các router con (auth, tenants, ...) gắn vào đây."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router
from app.api.v1.branches import router as branches_router
from app.api.v1.cash_transactions import router as cash_transactions_router
from app.api.v1.categories import router as categories_router
from app.api.v1.customers import router as customers_router
from app.api.v1.orders import router as orders_router
from app.api.v1.payments import router as payments_router
from app.api.v1.services import router as services_router
from app.api.v1.settings import router as settings_router
from app.api.v1.shifts import router as shifts_router
from app.api.v1.tenants import router as tenants_router
from app.api.v1.users import router as users_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)
api_router.include_router(tenants_router)
api_router.include_router(branches_router)
api_router.include_router(users_router)
api_router.include_router(shifts_router)
api_router.include_router(orders_router)
api_router.include_router(payments_router)
api_router.include_router(cash_transactions_router)
api_router.include_router(customers_router)
api_router.include_router(categories_router)
api_router.include_router(services_router)
api_router.include_router(settings_router)


@api_router.get("/ping")
async def ping() -> dict[str, str]:
    """Healthcheck đơn giản cho tầng API v1."""
    return {"message": "pong"}
