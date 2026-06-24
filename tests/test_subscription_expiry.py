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
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.order import Order
from app.services.branch_service import compute_expiry_status
from tests.conftest import auth_headers, login

ORDERS = "/api/v1/orders"
ME = "/api/v1/auth/me"
ADMIN_LOGIN = "/api/v1/admin/auth/login"
TENANTS = "/api/v1/admin/tenants"
PLANS = "/api/v1/admin/plans"
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


# ── /auth/me trả expiry (cho banner POS) ─────────────────────────────────────
async def _me(client: AsyncClient, token: str) -> dict:
    r = await client.get(ME, headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()


async def test_me_unlimited_is_active(client: AsyncClient, shop: dict):
    """current_period_end NULL → status active, expires/days_left None."""
    d = await _me(client, shop["token"])
    assert d["subscription_status"] == "active"
    assert d["subscription_expires_at"] is None
    assert d["subscription_days_left"] is None


async def test_me_warning(client: AsyncClient, shop: dict):
    await _set_expiry(shop["tenant_id"], _now() + timedelta(days=2))
    d = await _me(client, shop["token"])
    assert d["subscription_status"] == "warning"
    assert d["subscription_days_left"] == 2
    assert d["subscription_expires_at"] is not None


async def test_me_grace(client: AsyncClient, shop: dict):
    await _set_expiry(shop["tenant_id"], _now() - timedelta(days=1))
    d = await _me(client, shop["token"])
    assert d["subscription_status"] == "grace"
    assert d["subscription_days_left"] == GRACE - 1


async def test_me_expired(client: AsyncClient, shop: dict):
    await _set_expiry(shop["tenant_id"], _now() - timedelta(days=GRACE + 2))
    d = await _me(client, shop["token"])
    assert d["subscription_status"] == "expired"
    assert d["subscription_expires_at"] is not None


# ── Super Admin set expires_at (endpoint + detail + list) ────────────────────
@pytest_asyncio.fixture
async def admin() -> dict:
    pw = "admin-secret-123"
    async with SessionFactory() as db:
        a = Admin(
            phone="0999999990", full_name="Super Admin", role="super_admin",
            password_hash=hash_password(pw), status="active",
        )
        db.add(a)
        await db.commit()
        return {"phone": a.phone, "password": pw}


async def _admin_tok(client: AsyncClient, admin: dict) -> str:
    r = await client.post(ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _mk_tenant(client, atok, slug, phone, pw) -> dict:
    r = await client.post(
        TENANTS,
        json={"name": f"Shop {slug}", "slug": slug, "owner_full_name": "O",
              "owner_phone": phone, "owner_password": pw},
        headers=auth_headers(atok),
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _set_sub(client, atok, tid, plan_id, **extra):
    return await client.put(
        f"{TENANTS}/{tid}/subscription",
        json={"plan_id": plan_id, **extra}, headers=auth_headers(atok),
    )


async def test_admin_set_expires_at_roundtrip(client: AsyncClient, admin: dict):
    """Set hạn tương lai → endpoint trả expiry; đọc lại qua detail khớp."""
    atok = await _admin_tok(client, admin)
    t = await _mk_tenant(client, atok, "exp-shop", "0904000001", "passw1")
    tid = t["tenant_id"]
    plans = (await client.get(PLANS, headers=auth_headers(atok))).json()
    exp = (_now() + timedelta(days=10)).isoformat()

    rs = await _set_sub(client, atok, tid, plans[0]["id"], expires_at=exp)
    assert rs.status_code == 200, rs.text
    assert rs.json()["expires_at"] is not None
    assert rs.json()["expiry_status"] == "active"  # 10 ngày > WARN=7
    assert rs.json()["days_left"] == 10

    d = (await client.get(f"{TENANTS}/{tid}", headers=auth_headers(atok))).json()
    assert d["expires_at"] is not None
    assert d["expiry_status"] == "active"
    assert d["days_left"] == 10


async def test_admin_set_expires_null_is_unlimited(client: AsyncClient, admin: dict):
    """Đặt hạn rồi gửi expires_at=None → xóa hạn (vô hạn → active)."""
    atok = await _admin_tok(client, admin)
    t = await _mk_tenant(client, atok, "exp-null", "0904000002", "passw1")
    tid, pid = t["tenant_id"], (await client.get(PLANS, headers=auth_headers(atok))).json()[0]["id"]

    await _set_sub(client, atok, tid, pid, expires_at=(_now() - timedelta(days=1)).isoformat())
    rs = await _set_sub(client, atok, tid, pid, expires_at=None)
    assert rs.status_code == 200, rs.text
    assert rs.json()["expires_at"] is None
    assert rs.json()["expiry_status"] == "active"


async def test_admin_set_expires_past_is_expired(client: AsyncClient, admin: dict):
    """Set hạn quá khứ (quá ân hạn) → endpoint trả expired."""
    atok = await _admin_tok(client, admin)
    t = await _mk_tenant(client, atok, "exp-past", "0904000004", "passw1")
    tid, pid = t["tenant_id"], (await client.get(PLANS, headers=auth_headers(atok))).json()[0]["id"]
    rs = await _set_sub(client, atok, tid, pid, expires_at=(_now() - timedelta(days=GRACE + 2)).isoformat())
    assert rs.status_code == 200, rs.text
    assert rs.json()["expiry_status"] == "expired"


async def test_admin_list_has_expiry_status(client: AsyncClient, admin: dict):
    """List tenant trả expiry_status mỗi dòng (để liếc tenant sắp/đã hết hạn)."""
    atok = await _admin_tok(client, admin)
    t = await _mk_tenant(client, atok, "list-exp", "0904000003", "passw1")
    pid = (await client.get(PLANS, headers=auth_headers(atok))).json()[0]["id"]
    await _set_sub(client, atok, t["tenant_id"], pid,
                   expires_at=(_now() - timedelta(days=GRACE + 2)).isoformat())

    lst = (await client.get(TENANTS, headers=auth_headers(atok))).json()
    row = next(x for x in lst if x["id"] == t["tenant_id"])
    assert row["expiry_status"] == "expired"
    assert "days_left" in row and "expires_at" in row
