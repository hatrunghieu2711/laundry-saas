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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.core.database import SessionFactory, _AppSyncSession
from app.core.redis import redis_client
from app.core.security import hash_password
from app.models.branch import Branch
from app.models.log import OrderTrackingLog
from app.models.order import Order
from app.models.tenant import Tenant
from app.models.user import User
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
    return {
        "owner_token": owner_token, "staff_token": staff_token,
        "branch": branch, "slug": owner["slug"],
    }


# ── dữ liệu công khai đúng ───────────────────────────────────────────────────
async def test_public_track_returns_status_branch_timeline(
    client: AsyncClient, track_ctx: dict
):
    o = await _create_order(client, track_ctx["staff_token"])
    await _advance(client, track_ctx["staff_token"], o["id"], "washing")
    await _advance(client, track_ctx["staff_token"], o["id"], "drying")

    # KHÔNG gửi Authorization — trang công khai.
    r = await client.get(f"{TRACK}/{track_ctx['slug']}/{o['order_code']}", headers=_ip("203.0.113.10"))
    assert r.status_code == 200, r.text
    data = r.json()

    assert data["order_code"] == o["order_code"]
    assert data["order_status"] == "drying"
    assert data["tenant_name"] == "Giặt Ủi 2H"  # header/footer track-site
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

    r = await client.get(f"{TRACK}/{track_ctx['slug']}/{o['order_code']}", headers=_ip("203.0.113.11"))
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
    r = await client.get(f"{TRACK}/{track_ctx['slug']}/B9-99999", headers=_ip("203.0.113.12"))
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
            r = await client.get(f"{TRACK}/{track_ctx['slug']}/{o['order_code']}", headers=_ip(ip))
            codes.append(r.status_code)
        assert codes[:3] == [200, 200, 200], codes
        assert codes[3] == 429, codes

        r = await client.get(f"{TRACK}/{track_ctx['slug']}/{o['order_code']}", headers=_ip(ip))
        assert r.json()["code"] == "RATE_LIMITED"

        # IP khác KHÔNG bị ảnh hưởng (bucket riêng).
        r2 = await client.get(f"{TRACK}/{track_ctx['slug']}/{o['order_code']}", headers=_ip("203.0.113.98"))
        assert r2.status_code == 200, r2.text
    finally:
        s.public_track_rate_limit = old
        await redis_client.delete(f"rl:track:{ip}")
        await redis_client.delete("rl:track:203.0.113.98")


# ── multi-tenant: slug định danh tenant ──────────────────────────────────────
async def test_public_track_slug_not_found_404(client: AsyncClient, track_ctx: dict):
    """slug không tồn tại → 404 (không lộ slug tồn tại hay không)."""
    o = await _create_order(client, track_ctx["staff_token"])
    r = await client.get(f"{TRACK}/khong-co-tiem/{o['order_code']}", headers=_ip("203.0.113.22"))
    assert r.status_code == 404
    assert r.json()["code"] == "ORDER_NOT_FOUND"


async def test_public_track_inactive_tenant_404(
    client: AsyncClient, track_ctx: dict, owner: dict
):
    """tenant khóa (status != active) → 404 (không tra được)."""
    o = await _create_order(client, track_ctx["staff_token"])
    async with SessionFactory() as db:
        t = await db.get(Tenant, owner["tenant_id"])
        t.status = "suspended"
        await db.commit()
    r = await client.get(
        f"{TRACK}/{track_ctx['slug']}/{o['order_code']}", headers=_ip("203.0.113.23")
    )
    assert r.status_code == 404
    assert r.json()["code"] == "ORDER_NOT_FOUND"


async def test_public_track_multitenant_resolves_by_slug(
    client: AsyncClient, owner: dict, owner2: dict
):
    """⭐ 2 tenant TRÙNG order_code (B1-00001) → tra theo slug ra ĐÚNG đơn tenant đó."""
    t1 = await login(client, owner["phone"], owner["password"])
    b1 = (await client.post("/api/v1/branches", json={"name": "CN Một"}, headers=auth_headers(t1))).json()
    o1 = (await client.post(
        "/api/v1/orders",
        json={"items": [{"service_name": "Giặt", "quantity": 1, "unit_price": 10000}],
              "pickup_at": _pickup(), "branch_id": b1["id"]},
        headers=auth_headers(t1),
    )).json()

    t2 = await login(client, owner2["phone"], owner2["password"])
    b2 = (await client.post("/api/v1/branches", json={"name": "CN Hai"}, headers=auth_headers(t2))).json()
    o2 = (await client.post(
        "/api/v1/orders",
        json={"items": [{"service_name": "Giặt", "quantity": 1, "unit_price": 10000}],
              "pickup_at": _pickup(), "branch_id": b2["id"]},
        headers=auth_headers(t2),
    )).json()

    # Cùng order_code (cả hai CN B1, prefix B1, đơn đầu → B1-00001).
    assert o1["order_code"] == o2["order_code"] == "B1-00001"

    r1 = await client.get(f"{TRACK}/{owner['slug']}/B1-00001", headers=_ip("203.0.113.24"))
    r2 = await client.get(f"{TRACK}/{owner2['slug']}/B1-00001", headers=_ip("203.0.113.25"))
    assert r1.status_code == 200 and r2.status_code == 200, (r1.text, r2.text)
    assert r1.json()["branch"]["name"] == "CN Một"
    assert r2.json()["branch"]["name"] == "CN Hai"


# ── gom nhóm trạng thái + ẩn đơn ĐÃ HỦY ──────────────────────────────────────
async def test_public_track_cancelled_is_404(client: AsyncClient, track_ctx: dict):
    """⭐ Đơn hủy → 404 ORDER_NOT_FOUND (ẩn hoàn toàn, không lộ đơn từng tồn tại)."""
    o = await _create_order(client, track_ctx["staff_token"])
    async with SessionFactory() as db:
        order = await db.scalar(select(Order).where(Order.order_code == o["order_code"]))
        order.order_status = "cancelled"
        await db.commit()
    r = await client.get(
        f"{TRACK}/{track_ctx['slug']}/{o['order_code']}", headers=_ip("203.0.113.30")
    )
    assert r.status_code == 404
    assert r.json()["code"] == "ORDER_NOT_FOUND"


async def test_public_track_status_group_map(client: AsyncClient, track_ctx: dict):
    """Map đủ status còn lại → (group, label); GIỮ order_status raw + timeline."""
    o = await _create_order(client, track_ctx["staff_token"])
    code, slug = o["order_code"], track_ctx["slug"]
    cases = [
        ("created", "processing", "Đang xử lý"),
        ("washing", "processing", "Đang xử lý"),
        ("drying", "processing", "Đang xử lý"),
        ("ready", "ready", "Đã xong — mời lấy"),
        ("delivered", "delivered", "Đã giao"),
        ("completed", "delivered", "Đã giao"),
    ]
    for i, (st, grp, lbl) in enumerate(cases):
        async with SessionFactory() as db:
            order = await db.scalar(select(Order).where(Order.order_code == code))
            order.order_status = st
            await db.commit()
        r = await client.get(f"{TRACK}/{slug}/{code}", headers=_ip(f"203.0.113.{40 + i}"))
        assert r.status_code == 200, r.text
        d = r.json()
        assert d["order_status"] == st  # raw giữ nguyên
        assert d["status_group"] == grp, (st, d)
        assert d["status_label"] == lbl, (st, d)
        assert "timeline" in d  # timeline giữ


# ── ⭐ RLS THẬT: set_config là load-bearing (bắt bug cũ owner-bypass che) ──────
async def test_public_tracking_under_real_rls(app_role_engine):
    """Chạy get_public_tracking bằng laundry_app (non-bypass RLS). orders STRICT →
    thiếu set_config thì RLS chặn → 404. Trả đúng đơn ⇒ set_config hoạt động."""
    from app.services import public_service

    async with SessionFactory() as s:  # seed bằng OWNER (bypass)
        t = Tenant(name="RLS Track", slug="rls-track", status="active")
        s.add(t)
        await s.flush()
        b = Branch(tenant_id=t.id, name="CN RLS", code="B1", order_prefix="B1", status="active")
        s.add(b)
        u = User(tenant_id=t.id, role="owner", full_name="O", phone="0904000040",
                 password_hash=hash_password("x"), status="active")
        s.add(u)
        await s.flush()
        o = Order(tenant_id=t.id, branch_id=b.id, order_code="B1-00001",
                  pickup_at=datetime.now(timezone.utc), created_by=u.id)
        s.add(o)
        await s.flush()
        s.add(OrderTrackingLog(order_id=o.id, status="created", changed_by=u.id))
        await s.commit()

    factory = async_sessionmaker(
        bind=app_role_engine, class_=AsyncSession,
        sync_session_class=_AppSyncSession, expire_on_commit=False,
    )
    async with factory() as db:
        data = await public_service.get_public_tracking(db, "rls-track", "B1-00001")
    assert data["order_code"] == "B1-00001"
    assert data["order_status"] == "created"
    assert data["branch"]["name"] == "CN RLS"
