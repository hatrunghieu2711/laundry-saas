"""Router tổng hợp /api/v1. Các router con (auth, tenants, ...) gắn vào đây."""
from fastapi import APIRouter

from app.api.v1.auth import router as auth_router

api_router = APIRouter(prefix="/api/v1")
api_router.include_router(auth_router)


@api_router.get("/ping")
async def ping() -> dict[str, str]:
    """Healthcheck đơn giản cho tầng API v1."""
    return {"message": "pong"}
