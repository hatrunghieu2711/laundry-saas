"""Router tổng hợp /api/v1. Các router con (auth, tenants, ...) gắn vào đây ở Stage sau."""
from fastapi import APIRouter

api_router = APIRouter(prefix="/api/v1")


@api_router.get("/ping")
async def ping() -> dict[str, str]:
    """Healthcheck đơn giản cho tầng API v1."""
    return {"message": "pong"}
