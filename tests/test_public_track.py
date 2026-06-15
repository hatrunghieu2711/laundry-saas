"""Stage 5.2 — trang tracking công khai GET /public/track/{order_code}.

Kiểm:
- Trả đúng dữ liệu công khai (mã, trạng thái, timeline, liên hệ branch, pickup_at).
- KHÔNG auth vẫn xem được; KHÔNG lộ tiền / SĐT / tên khách đầy đủ.
- Mã sai → 404 ORDER_NOT_FOUND.
- Rate limit theo IP hoạt động → 429 RATE_LIMITED.
"""
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient

from app.core.config import get_settings
from app.core.redis import redis_client
from tests.conftest import auth_headers, login

TRACK = "/public/track"


def _pickup(hours: float = 4) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


def _ip(ip: str) -> dict[str, str]:
    # nginx đặt X-Real-IP = IP thật; mỗi test dùng IP riêng để tách bucket rate limit.
    return {"X-Real-IP": ip}


async def _create_order(client: AsyncClient, token: str, **extra) -> dict:
    body = {
        "items": [{"service_name": "Giặt sấy", "quantity": 3, "unit_price": 40000}],
        "pickup_at": _pickup(),
        **extra,
    }
    r = await client.post("/api/v1/orders", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _advance(client: AsyncClient, token: str, oid: str, status: str) -> None:
    r = await client.patch(
        f"/api/v1/orders/{oid}/status",
        json={"order_status": status},
        headers=auth_headers(token),
    )
    assert r.status_code == 200, r.text


@pytest_asyncio.fixture
async def track_ctx(client: AsyncClient, owner: dict) -> dict:
    """Owner + 1 branch (có địa chỉ + SĐT) + staff ở branch đó."""
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post(
        "/api/v1/branches",
        json={
            "name": "Giặt Ủi 2H - CN Trần Phú",
            "address": "12 Trần Phú, Nha Trang",
            "phone": "0258123456",
        },
        headers=auth_headers(owner_token),
    )
    assert r.status_code == 201, r.text
    branch = r.json()
    r = await client.post(
        "/api/v1/users",
        json={
            "full_name": "NV A",
            "phone": "0900000041",
            "password": "pass123",
            "role": "staff",
            "branch_id": branch["id"],
        },
        headers=auth_headers(owner_token),
    )
    assert r.status_code == 201, r.text
    staff_token = await login(client, "0900000041", "pass123")
    return {"owner_token": owner_token, "staff_token": staff_token, "branch": branch}


# ── dữ liệu công khai đúng ───────────────────────────────────────────────────
async def test_public_track_returns_status_branch_timeline(
    client: AsyncClient, track_ctx: dict
):
    o = await _create_order(client, track_ctx["staff_token"])
    await _advance(client, track_ctx["staff_token"], o["id"], "washing")
    await _advance(client, track_ctx["staff_token"], o["id"], "drying")

    # KHÔNG gửi Authorization — trang công khai.
    r = await client.get(f"{TRACK}/{o['order_code']}", headers=_ip("203.0.113.10"))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["order_code"] == o["order_code"]
    assert data["order_status"] == "drying"
    assert data["pickup_at"]
    assert data["branch"]["name"] == "Giặt Ủi 2H - CN Trần Phú"
    assert data["branch"]["address"] == "12 Trần Phú, Nha Trang"
    assert data["branch"]["phone"] == "0258123456"

    statuses = [t["status"] for t in data["timeline"]]
    assert statuses == ["created", "washing", "drying"]  # đúng thứ tự thời gian
    assert all(t["at"] for t in data["timeline"])


# ── KHÔNG lộ tiền / khách ────────────────────────────────────────────────────
async def test_public_track_hides_money_and_customer(
    client: AsyncClient, track_ctx: dict
):
    rc = await client.post(
        "/api/v1/customers",
        json={"full_name": "Nguyễn Văn Hùng", "phone": "0912345678"},
        headers=auth_headers(track_ctx["staff_token"]),
    )
    assert rc.status_code == 201, rc.text
    cust = rc.json()
    o = await _create_order(client, track_ctx["staff_token"], customer_id=cust["id"])

    r = await client.get(f"{TRACK}/{o['order_code']}", headers=_ip("203.0.113.11"))
    assert r.status_code == 200, r.text
    data = r.json()
    raw = r.text

    # KHÔNG có bất kỳ field tiền / khách / id nội bộ nào.
    for forbidden in (
        "total_amount",
        "payment_status",
        "paid",
        "amount",
        "customer",
        "customer_name",
        "customer_id",
        "tenant_id",
        "branch_id",
        "notes",
    ):
        assert forbidden not in data, f"rò rỉ field công khai: {forbidden}"

    # KHÔNG lộ SĐT / tên đầy đủ của khách trong toàn payload.
    assert "0912345678" not in raw
    assert "Nguyễn Văn Hùng" not in raw


# ── mã sai → 404 ─────────────────────────────────────────────────────────────
async def test_public_track_unknown_code_404(client: AsyncClient, track_ctx: dict):
    r = await client.get(f"{TRACK}/B9-99999", headers=_ip("203.0.113.12"))
    assert r.status_code == 404, r.text
    assert r.json()["code"] == "ORDER_NOT_FOUND"


# ── rate limit theo IP ───────────────────────────────────────────────────────
async def test_public_track_rate_limited(client: AsyncClient, track_ctx: dict):
    o = await _create_order(client, track_ctx["staff_token"])
    ip = "203.0.113.99"
    await redis_client.delete(f"rl:track:{ip}")  # bucket sạch trước khi test

    s = get_settings()
    old = s.public_track_rate_limit
    s.public_track_rate_limit = 3
    try:
        codes = []
        for _ in range(4):
            r = await client.get(f"{TRACK}/{o['order_code']}", headers=_ip(ip))
            codes.append(r.status_code)
        assert codes[:3] == [200, 200, 200], codes
        assert codes[3] == 429, codes

        r = await client.get(f"{TRACK}/{o['order_code']}", headers=_ip(ip))
        assert r.json()["code"] == "RATE_LIMITED"

        # IP khác KHÔNG bị ảnh hưởng (bucket riêng).
        r2 = await client.get(f"{TRACK}/{o['order_code']}", headers=_ip("203.0.113.98"))
        assert r2.status_code == 200, r2.text
    finally:
        s.public_track_rate_limit = old
        await redis_client.delete(f"rl:track:{ip}")
        await redis_client.delete("rl:track:203.0.113.98")
