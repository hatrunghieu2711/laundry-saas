"""Entrypoint FastAPI — Laundry SaaS. Skeleton: hello world chạy được qua docker compose."""
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from app.api.v1.router import api_router
from app.core.config import get_settings

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup: kết nối (engine/redis tạo lazy) — chưa cần khởi tạo gì ở skeleton.
    yield
    # Shutdown: đóng tài nguyên ở Stage sau (engine.dispose, redis.close).


app = FastAPI(
    title="Laundry SaaS — Financial Control & Operations Platform",
    version="0.1.0",
    debug=settings.debug,
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/")
async def root() -> dict[str, str]:
    return {"message": "Laundry SaaS API — hello world", "env": settings.app_env}


@app.get("/health")
async def health() -> JSONResponse:
    """Healthcheck cho nginx/uptime. Chưa ping DB/Redis ở skeleton."""
    return JSONResponse({"status": "ok"})
