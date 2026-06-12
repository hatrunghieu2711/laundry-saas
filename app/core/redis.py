"""Redis client (rate limit, cache) — async."""
from redis.asyncio import Redis, from_url

from app.core.config import get_settings

_settings = get_settings()

redis_client: Redis = from_url(_settings.redis_url, decode_responses=True)


async def get_redis() -> Redis:
    """FastAPI dependency: trả Redis client dùng chung."""
    return redis_client
