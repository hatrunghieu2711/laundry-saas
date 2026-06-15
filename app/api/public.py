"""Router CÔNG KHAI (KHÔNG auth) — chỉ /public/track/{order_code}.

Gắn TRỰC TIẾP lên app (ngoài /api/v1). nginx track.giatui2h.com proxy /public/*
về backend. Rate limit theo IP (Redis) chống quét mã.
"""
from fastapi import APIRouter, Depends, Request
from redis.asyncio import Redis

from app.api.deps import DbSession
from app.core.config import get_settings
from app.core.ratelimit import client_ip, enforce_rate_limit
from app.core.redis import get_redis
from app.schemas.public import PublicTrackOut
from app.services import public_service

router = APIRouter(prefix="/public", tags=["public"])


async def _rate_limit_track(
    request: Request, redis: Redis = Depends(get_redis)
) -> None:
    s = get_settings()
    await enforce_rate_limit(
        redis,
        client_ip(request),
        scope="track",
        limit=s.public_track_rate_limit,
        window=s.public_track_rate_window,
    )


@router.get(
    "/track/{order_code}",
    response_model=PublicTrackOut,
    dependencies=[Depends(_rate_limit_track)],
)
async def track_order(order_code: str, db: DbSession) -> PublicTrackOut:
    data = await public_service.get_public_tracking(db, order_code)
    return PublicTrackOut(**data)
