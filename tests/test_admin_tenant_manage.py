"""Test A3: admin list/detail/sửa/khóa tenant + reset MK owner.

⚠️ ĐIỂM SỐNG CÒN:
- KHÓA tenant phải REVOKE refresh token mọi user của tenant (không thì rotate_session
  không check tenant.status → khóa GIẢ, refresh vô thời hạn).
- list stats đếm bảng strict (branches/orders) qua set_config loop — test RLS THẬT
  (laundry_app non-bypass) chứng minh set_config load-bearing.
"""
import uuid
from datetime import datetime, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SessionFactory, _AppSyncSession
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.branch import Branch
from app.models.order import Order
from app.models.tenant import Tenant
from app.models.user import User
from tests.conftest import auth_headers, login

ADMIN_LOGIN = "/api/v1/admin/auth/login"
TENANTS = "/api/v1/admin/tenants"
USER_LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
BRANCHES = "/api/v1/branches"
USERS = "/api/v1/users"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"


@pytest_asyncio.fixture
async def admin() -> dict:
    password = "admin-secret-123"
    async with SessionFactory() as db:
        a = Admin(
            phone="0999999999", full_name="Super Admin", role="super_admin",
            password_hash=hash_password(password), status="active",
        )
        db.add(a)
        await db.commit()
        return {"id": a.id, "phone": a.phone, "password": password}


async def _admin_token(client: AsyncClient, admin: dict) -> str:
    resp = await client.post(
        ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _create_tenant(client, atok, slug, owner_phone, *, name="Shop", owner_password=None):
    body = {"name": name, "slug": slug, "owner_full_name": f"Owner {slug}", "owner_phone": owner_phone}
    if owner_password:
        body["owner_password"] = owner_password
    resp = await client.post(TENANTS, json=body, headers=auth_headers(atok))
    assert resp.status_code == 201, resp.text
    return resp.json()


def _set_cookies(client: AsyncClient, **cookies: str) -> None:
    client.cookies.clear()
    for k, v in cookies.items():
        client.cookies.set(k, v)


async def _full_login(client, phone, password, slug) -> tuple[str, str]:
    """Login user thường, trả (refresh_raw, csrf) để test refresh sau khóa/reset."""
    resp = await client.post(USER_LOGIN, json={"phone": phone, "password": password, "slug": slug})
    assert resp.status_code == 200, resp.text
    return resp.cookies.get(REFRESH_COOKIE), resp.json()["csrf_token"]


# ── list + stats ────────────────────────────────────────────────────────────
async def test_list_tenants_with_stats(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "shop-a", "0900100001", owner_password="ownerA-123")
    await _create_tenant(client, atok, "shop-b", "0900200002", owner_password="ownerB-123")

    # Plans-1: tenant mới mặc định Gói 1 (max 1 CN) → nâng gói shop-a để thêm CN thứ 2.
    plans = (await client.get("/api/v1/admin/plans", headers=auth_headers(atok))).json()
    rsub = await client.put(
        f"{TENANTS}/{a['tenant_id']}/subscription",
        json={"plan_id": plans[0]["id"], "custom_max_branches": 9},
        headers=auth_headers(atok),
    )
    assert rsub.status_code == 200, rsub.text

    # owner A thêm 1 CN + 1 staff → A: 2 branches, 2 users.
    aown = await client.post(
        USER_LOGIN, json={"phone": "0900100001", "password": "ownerA-123", "slug": "shop-a"}
    )
    atoken = aown.json()["access_token"]
    rb = await client.post(BRANCHES, json={"name": "CN2"}, headers=auth_headers(atoken))
    assert rb.status_code == 201, rb.text
    rs = await client.post(
        USERS,
        json={"full_name": "NV", "phone": "0900100050", "password": "pass123",
              "role": "staff", "branch_id": rb.json()["id"]},
        headers=auth_headers(atoken),
    )
    assert rs.status_code == 201, rs.text

    lst = await client.get(TENANTS, headers=auth_headers(atok))
    assert lst.status_code == 200, lst.text
    by_slug = {t["slug"]: t for t in lst.json()}
    assert by_slug["shop-a"]["n_branches"] == 2
    assert by_slug["shop-a"]["n_users"] == 2
    assert by_slug["shop-a"]["last_order_at"] is None
    assert by_slug["shop-b"]["n_branches"] == 1
    assert by_slug["shop-b"]["n_users"] == 1


async def test_get_tenant_detail(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "detail-shop", "0900300003")
    r = await client.get(f"{TENANTS}/{a['tenant_id']}", headers=auth_headers(atok))
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["slug"] == "detail-shop"
    assert body["n_branches"] == 1 and body["n_users"] == 1


async def test_get_tenant_detail_404(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    r = await client.get(f"{TENANTS}/{uuid.uuid4()}", headers=auth_headers(atok))
    assert r.status_code == 404


# ── ⭐ RLS THẬT: set_config loop đếm strict (laundry_app non-bypass) ───────────
async def test_list_stats_under_real_rls(app_role_engine):
    """Chạy list_tenants_with_stats bằng role laundry_app (RLS có hiệu lực).

    branches/orders strict → set_config(tenant) là load-bearing: thiếu nó RLS trả 0.
    Đếm ra đúng → chứng minh set_config loop hoạt động xuyên RLS."""
    from app.services import admin_tenant_service

    async with SessionFactory() as s:  # seed bằng OWNER (bypass)
        ta = Tenant(name="RA", slug="rls-stats-a", status="active")
        s.add(ta)
        await s.flush()
        ba1 = Branch(tenant_id=ta.id, name="A1", code="B1", order_prefix="B1", status="active")
        s.add(ba1)
        s.add(Branch(tenant_id=ta.id, name="A2", code="B2", order_prefix="B2", status="active"))
        ua = User(tenant_id=ta.id, role="owner", full_name="OA", phone="0902000020",
                  password_hash=hash_password("x"), status="active")
        s.add(ua)
        await s.flush()
        s.add(Order(tenant_id=ta.id, branch_id=ba1.id, order_code="B1-00001",
                    pickup_at=datetime.now(timezone.utc), created_by=ua.id))

        tb = Tenant(name="RB", slug="rls-stats-b", status="active")
        s.add(tb)
        await s.flush()
        s.add(Branch(tenant_id=tb.id, name="B1b", code="B1", order_prefix="B1", status="active"))
        s.add(User(tenant_id=tb.id, role="owner", full_name="OB", phone="0902100021",
                   password_hash=hash_password("x"), status="active"))
        await s.commit()

    factory = async_sessionmaker(
        bind=app_role_engine, class_=AsyncSession,
        sync_session_class=_AppSyncSession, expire_on_commit=False,
    )
    async with factory() as db:
        stats = await admin_tenant_service.list_tenants_with_stats(db)

    by = {row.slug: row for row in stats}
    assert by["rls-stats-a"].n_branches == 2
    assert by["rls-stats-a"].n_users == 1
    assert by["rls-stats-a"].last_order_at is not None
    assert by["rls-stats-b"].n_branches == 1
    assert by["rls-stats-b"].last_order_at is None


# ── update name/slug ──────────────────────────────────────────────────────────
async def test_update_tenant_name_and_slug(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "old-slug", "0900400004")
    r = await client.patch(
        f"{TENANTS}/{a['tenant_id']}",
        json={"name": "Tên Mới", "slug": "new-slug"}, headers=auth_headers(atok),
    )
    assert r.status_code == 200, r.text
    assert r.json()["slug"] == "new-slug"
    assert r.json()["name"] == "Tên Mới"
    assert r.json()["slug_changed"] is True
    # login bằng slug MỚI OK; slug CŨ → 401.
    ok = await client.post(
        USER_LOGIN, json={"phone": "0900400004", "password": a["temp_password"], "slug": "new-slug"}
    )
    assert ok.status_code == 200, ok.text
    bad = await client.post(
        USER_LOGIN, json={"phone": "0900400004", "password": a["temp_password"], "slug": "old-slug"}
    )
    assert bad.status_code == 401


async def test_update_slug_duplicate_409(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    await _create_tenant(client, atok, "taken-slug", "0900500005")
    b = await _create_tenant(client, atok, "other-slug", "0900600006")
    r = await client.patch(
        f"{TENANTS}/{b['tenant_id']}", json={"slug": "taken-slug"}, headers=auth_headers(atok)
    )
    assert r.status_code == 409
    assert r.json()["code"] == "SLUG_EXISTS"


async def test_update_slug_invalid_422(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "valid-slug", "0900700007")
    r = await client.patch(
        f"{TENANTS}/{a['tenant_id']}", json={"slug": "BAD SLUG!"}, headers=auth_headers(atok)
    )
    assert r.status_code == 422


# ── ⭐ KHÓA tenant + revoke refresh (sống còn) ────────────────────────────────
async def test_lock_tenant_revokes_refresh(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "lock-a", "0900800008", owner_password="lockA-123")
    await _create_tenant(client, atok, "lock-b", "0900900009", owner_password="lockB-123")

    a_refresh, a_csrf = await _full_login(client, "0900800008", "lockA-123", "lock-a")
    b_refresh, b_csrf = await _full_login(client, "0900900009", "lockB-123", "lock-b")

    rk = await client.post(f"{TENANTS}/{a['tenant_id']}/lock", headers=auth_headers(atok))
    assert rk.status_code == 200, rk.text
    assert rk.json()["status"] == "suspended"

    # owner A refresh → FAIL (token revoked) → khóa HIỆU LỰC.
    _set_cookies(client, **{REFRESH_COOKIE: a_refresh, CSRF_COOKIE: a_csrf})
    ra = await client.post(REFRESH, headers={"X-CSRF-Token": a_csrf})
    assert ra.status_code == 401
    assert ra.json()["code"] == "INVALID_REFRESH_TOKEN"

    # owner B (tenant khác) refresh → VẪN OK (không bị revoke chéo).
    _set_cookies(client, **{REFRESH_COOKIE: b_refresh, CSRF_COOKIE: b_csrf})
    rb = await client.post(REFRESH, headers={"X-CSRF-Token": b_csrf})
    assert rb.status_code == 200, rb.text

    # owner A login lại → chặn bởi guard tenant khóa (GĐ2).
    la2 = await client.post(
        USER_LOGIN, json={"phone": "0900800008", "password": "lockA-123", "slug": "lock-a"}
    )
    assert la2.status_code == 403
    assert la2.json()["code"] == "TENANT_INACTIVE"


async def test_unlock_tenant(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "unlock-a", "0901000010", owner_password="unlockA-123")
    await client.post(f"{TENANTS}/{a['tenant_id']}/lock", headers=auth_headers(atok))

    blocked = await client.post(
        USER_LOGIN, json={"phone": "0901000010", "password": "unlockA-123", "slug": "unlock-a"}
    )
    assert blocked.status_code == 403

    ru = await client.post(f"{TENANTS}/{a['tenant_id']}/unlock", headers=auth_headers(atok))
    assert ru.status_code == 200
    assert ru.json()["status"] == "active"

    ok = await client.post(
        USER_LOGIN, json={"phone": "0901000010", "password": "unlockA-123", "slug": "unlock-a"}
    )
    assert ok.status_code == 200, ok.text


# ── ⭐ reset MK owner ─────────────────────────────────────────────────────────
async def test_reset_owner_password(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "reset-a", "0901100011", owner_password="oldpass-123")
    old_refresh, old_csrf = await _full_login(client, "0901100011", "oldpass-123", "reset-a")

    rr = await client.post(
        f"{TENANTS}/{a['tenant_id']}/reset-owner-password", json={}, headers=auth_headers(atok)
    )
    assert rr.status_code == 200, rr.text
    new_pw = rr.json()["temp_password"]
    assert rr.json()["owner_phone"] == "0901100011"
    assert new_pw and new_pw != "oldpass-123"

    # MK mới login OK; MK cũ FAIL.
    ln = await client.post(
        USER_LOGIN, json={"phone": "0901100011", "password": new_pw, "slug": "reset-a"}
    )
    assert ln.status_code == 200, ln.text
    lc = await client.post(
        USER_LOGIN, json={"phone": "0901100011", "password": "oldpass-123", "slug": "reset-a"}
    )
    assert lc.status_code == 401

    # refresh CŨ của owner bị revoke.
    _set_cookies(client, **{REFRESH_COOKIE: old_refresh, CSRF_COOKIE: old_csrf})
    rf = await client.post(REFRESH, headers={"X-CSRF-Token": old_csrf})
    assert rf.status_code == 401
    assert rf.json()["code"] == "INVALID_REFRESH_TOKEN"


async def test_reset_owner_none_404(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "no-owner", "0901300013")
    async with SessionFactory() as db:
        u = (
            await db.execute(
                select(User).where(
                    User.tenant_id == uuid.UUID(a["tenant_id"]), User.role == "owner"
                )
            )
        ).scalar_one()
        u.status = "inactive"
        await db.commit()
    rr = await client.post(
        f"{TENANTS}/{a['tenant_id']}/reset-owner-password", json={}, headers=auth_headers(atok)
    )
    assert rr.status_code == 404
    assert rr.json()["code"] == "NO_OWNER"


async def test_reset_owner_multiple_requires_user_id(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    a = await _create_tenant(client, atok, "multi-owner", "0901200012", owner_password="o1-123")
    tid = a["tenant_id"]
    aown = await client.post(
        USER_LOGIN, json={"phone": "0901200012", "password": "o1-123", "slug": "multi-owner"}
    )
    otok = aown.json()["access_token"]
    r2 = await client.post(
        USERS,
        json={"full_name": "Owner2", "phone": "0901200099", "password": "o2-123", "role": "owner"},
        headers=auth_headers(otok),
    )
    assert r2.status_code == 201, r2.text

    # nhiều owner + không user_id → 409.
    rr = await client.post(
        f"{TENANTS}/{tid}/reset-owner-password", json={}, headers=auth_headers(atok)
    )
    assert rr.status_code == 409
    assert rr.json()["code"] == "MULTIPLE_OWNERS"

    # chỉ định user_id → OK.
    rr2 = await client.post(
        f"{TENANTS}/{tid}/reset-owner-password",
        json={"user_id": r2.json()["id"]}, headers=auth_headers(atok),
    )
    assert rr2.status_code == 200, rr2.text
    assert rr2.json()["owner_phone"] == "0901200099"


# ── require_admin (cách ly A1) ───────────────────────────────────────────────
async def test_a3_requires_admin(client: AsyncClient, owner: dict):
    utok = await login(client, owner["phone"], owner["password"])
    tid = uuid.uuid4()
    for resp in [
        await client.get(TENANTS, headers=auth_headers(utok)),
        await client.get(f"{TENANTS}/{tid}", headers=auth_headers(utok)),
        await client.patch(f"{TENANTS}/{tid}", json={"name": "X"}, headers=auth_headers(utok)),
        await client.post(f"{TENANTS}/{tid}/lock", headers=auth_headers(utok)),
        await client.post(f"{TENANTS}/{tid}/reset-owner-password", json={}, headers=auth_headers(utok)),
    ]:
        assert resp.status_code == 401
        assert resp.json()["code"] == "INVALID_TOKEN"
