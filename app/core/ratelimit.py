"""Rate limit theo IP bằng Redis (fixed-window). Dùng cho endpoint công khai
(GET /public/track/{order_code}) chống quét mã hàng loạt."""
from fastapi import Request
from redis.asyncio import Redis

from app.core.errors import APIError


def client_ip(request: Request) -> str:
    """IP client thật.

    nginx GHI ĐÈ `X-Real-IP = $remote_addr` (proxy_set_header — client KHÔNG giả
    mạo được) nên ưu tiên header này. Fallback: hop CUỐI của X-Forwarded-For (do
    nginx thêm), rồi tới peer trực tiếp.
    """
    xri = request.headers.get("x-real-ip")
    if xri:
        return xri.strip()
    xff = request.headers.get("x-forwarded-for")
    if xff:
        return xff.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


async def enforce_rate_limit(
    redis: Redis, ip: str, *, scope: str, limit: int, window: int
) -> None:
    """Fixed-window: INCR key, set TTL ở lần đầu; vượt `limit` → 429.

    FAIL-OPEN nếu Redis lỗi: ưu tiên trang công khai luôn truy cập được (mất rate
    limit tạm thời khi Redis sự cố chấp nhận hơn là sập trang tra cứu của khách).
    """
    key = f"rl:{scope}:{ip}"
    try:
        count = await redis.incr(key)
        if count == 1:
            await redis.expire(key, window)
    except Exception:
        return  # fail-open
    if count > limit:
        raise APIError(429, "RATE_LIMITED", "Quá nhiều yêu cầu, vui lòng thử lại sau")
