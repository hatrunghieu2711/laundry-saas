"""Stage Subscription-expiry: BE nền + ENFORCE chặn TẠO ĐƠN khi hết hạn (test-first).

TÁI DÙNG cột subscriptions.current_period_end làm HẠN GÓI (NULL = vô hạn). WARN=7, GRACE=3.
- compute_expiry_status: hàm THUẦN — 5 nhánh (None/expired/grace/warning/active).
- create_order: expired → 403 SUBSCRIPTION_EXPIRED; grace/warning/active/None → tạo được;
  bị chặn thì KHÔNG để lại đơn mồ côi (fail trước mọi ghi).
- ĐƠN CŨ (đổi trạng thái / thêm món) khi đã hết hạn → VẪN được (chỉ create_order bị chặn).
"""
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select, text

from app.core.database import SessionFactory
from app.models.order import Order
from app.services.branch_service import compute_expiry_status
from tests.conftest import auth_headers, login

ORDERS = "/api/v1/orders"
WARN, GRACE = 7, 3  # khớp config mặc định (subscription_warn_days / subscription_grace_days)
_ITEMS = [{"service_name": "Giặt thường", "quantity": 2, "unit_price": 30000}]


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _pickup(hours: float = 4) -> str:
    return (_now() + timedelta(hours=hours)).isoformat()


async def _set_expiry(tenant_id, expires_at) -> None:
    """Đặt current_period_end cho subscription active của tenant (harness=owner → bypass RLS)."""
    async with SessionFactory() as db:
        await db.execute(
            text("UPDATE subscriptions SET current_period_end = :e WHERE tenant_id = :t"),
            {"e": expires_at, "t": str(tenant_id)},
        )
        await db.commit()


async def _order_count(tenant_id) -> int:
    async with SessionFactory() as db:
        return (
            await db.scalar(
                select(func.count()).select_from(Order).where(Order.tenant_id == tenant_id)
            )
        ) or 0


@pytest_asyncio.fixture
async def shop(client: AsyncClient, owner: dict) -> dict:
    """owner + 1 branch. Subscription mặc định current_period_end NULL (vô hạn)."""
    tok = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"}, headers=auth_headers(tok))
    assert r.status_code == 201, r.text
    return {"tenant_id": owner["tenant_id"], "token": tok, "branch": r.json()}


async def _create_order(client: AsyncClient, shop: dict, **extra):
    # owner phải chỉ định branch_id (không gắn branch) → kèm branch của shop.
    body = {"items": _ITEMS, "pickup_at": _pickup(), "branch_id": shop["branch"]["id"], **extra}
    return await client.post(ORDERS, json=body, headers=auth_headers(shop["token"]))


# ── ⭐ Unit: compute_expiry_status (THUẦN — 5 nhánh) ─────────────────────────
def test_status_none_is_unlimited():
    """expires_at None → vô hạn ('active', None)."""
    assert compute_expiry_status(None, _now(), WARN, GRACE) == ("active", None)


def test_status_past_grace_is_expired():
    """now > hạn + grace → 'expired', days_left ≤ 0."""
    now = datetime(2026, 6, 25, 12, tzinfo=timezone.utc)
    status, days = compute_expiry_status(now - timedelta(days=GRACE + 1), now, WARN, GRACE)
    assert status == "expired"
    assert days <= 0


def test_status_within_grace():
    """hạn < now ≤ hạn+grace → 'grace', days = ân hạn CÒN LẠI (> 0)."""
    now = datetime(2026, 6, 25, 12, tzinfo=timezone.utc)
    status, days = compute_expiry_status(now - timedelta(days=1), now, WARN, GRACE)
    assert status == "grace"
    assert days == GRACE - 1  # hết hạn 1 ngày, ân hạn còn 2


def test_status_within_warning():
    """hạn−warn < now ≤ hạn → 'warning', days = TỚI HẠN (> 0)."""
    now = datetime(2026, 6, 25, 12, tzinfo=timezone.utc)
    status, days = compute_expiry_status(now + timedelta(days=1), now, WARN, GRACE)
    assert status == "warning"
    assert days == 1


def test_status_far_is_active():
    """Xa hạn (ngoài cửa warn) → 'active', days = tới hạn."""
    now = datetime(2026, 6, 25, 12, tzinfo=timezone.utc)
    status, days = compute_expiry_status(now + timedelta(days=30), now, WARN, GRACE)
    assert status == "active"
    assert days == 30


# ── ⭐ Enforce create_order ──────────────────────────────────────────────────
async def test_create_blocked_when_expired(client: AsyncClient, shop: dict):
    """Quá ân hạn → 403 SUBSCRIPTION_EXPIRED + KHÔNG đơn mồ côi (fail trước ghi)."""
    await _set_expiry(shop["tenant_id"], _now() - timedelta(days=GRACE + 1))
    r = await _create_order(client, shop)
    assert r.status_code == 403, r.text
    assert r.json()["code"] == "SUBSCRIPTION_EXPIRED"
    assert await _order_count(shop["tenant_id"]) == 0  # không tạo đơn mồ côi


async def test_create_allowed_in_grace(client: AsyncClient, shop: dict):
    """Trong ân hạn (hết hạn 1 ngày, GRACE=3) → vẫn tạo được."""
    await _set_expiry(shop["tenant_id"], _now() - timedelta(days=1))
    assert (await _create_order(client, shop)).status_code == 201


async def test_create_allowed_in_warning(client: AsyncClient, shop: dict):
    """Sắp hết hạn (còn 1 ngày) → vẫn tạo được."""
    await _set_expiry(shop["tenant_id"], _now() + timedelta(days=1))
    assert (await _create_order(client, shop)).status_code == 201


async def test_create_allowed_when_active(client: AsyncClient, shop: dict):
    """Còn hạn xa → tạo được."""
    await _set_expiry(shop["tenant_id"], _now() + timedelta(days=60))
    assert (await _create_order(client, shop)).status_code == 201


async def test_create_allowed_when_unlimited_null(client: AsyncClient, shop: dict):
    """current_period_end NULL (vô hạn — mặc định 4 tenant prod) → tạo được."""
    assert (await _create_order(client, shop)).status_code == 201


# ── ⚠️ ĐƠN CŨ không bị chặn khi hết hạn ──────────────────────────────────────
async def test_old_order_editable_when_expired(client: AsyncClient, shop: dict):
    """Tạo đơn khi còn hạn → hết hạn → đổi trạng thái + thêm món đơn cũ VẪN được."""
    r = await _create_order(client, shop)  # NULL = vô hạn lúc tạo
    assert r.status_code == 201, r.text
    oid = r.json()["id"]

    await _set_expiry(shop["tenant_id"], _now() - timedelta(days=GRACE + 5))  # quá hạn

    rs = await client.patch(
        f"{ORDERS}/{oid}/status", json={"order_status": "washing"},
        headers=auth_headers(shop["token"]),
    )
    assert rs.status_code == 200, rs.text  # đổi trạng thái đơn cũ — không chặn

    ri = await client.post(
        f"{ORDERS}/{oid}/items",
        json={"service_name": "Sấy", "quantity": 1, "unit_price": 15000},
        headers=auth_headers(shop["token"]),
    )
    assert ri.status_code == 201, ri.text  # thêm món đơn cũ — không chặn
