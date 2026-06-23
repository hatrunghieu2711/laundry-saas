"""Test Plans-1: enforce giới hạn chi nhánh theo gói + gán gói (admin).

⚠️ Chính sách: mọi tenant LUÔN có subscription; KHÔNG subscription → CHẶN tạo CN
(không 'unlimited mặc định'). Đếm ACTIVE branch (soft-delete không tính).
"""
import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.billing import Subscription
from app.models.tenant import Tenant
from app.models.user import User
from tests.conftest import auth_headers, login

ADMIN_LOGIN = "/api/v1/admin/auth/login"
TENANTS = "/api/v1/admin/tenants"
PLANS = "/api/v1/admin/plans"
USER_LOGIN = "/api/v1/auth/login"
BRANCHES = "/api/v1/branches"


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


async def _admin_token(client, admin):
    resp = await client.post(ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _create_tenant(client, atok, slug, owner_phone, owner_password):
    resp = await client.post(
        TENANTS,
        json={"name": f"Shop {slug}", "slug": slug, "owner_full_name": "Owner",
              "owner_phone": owner_phone, "owner_password": owner_password},
        headers=auth_headers(atok),
    )
    assert resp.status_code == 201, resp.text
    return resp.json()


async def _owner_login(client, phone, password, slug) -> str:
    resp = await client.post(USER_LOGIN, json={"phone": phone, "password": password, "slug": slug})
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


async def _branch(client, otok, name):
    return await client.post(BRANCHES, json={"name": name}, headers=auth_headers(otok))


async def _plans(client, atok):
    return (await client.get(PLANS, headers=auth_headers(atok))).json()


# ── ⭐ enforce giới hạn ───────────────────────────────────────────────────────
async def test_plan1_blocks_second_branch(client: AsyncClient, admin: dict):
    """Gói 1 (max 1) + đã có B1 → tạo CN thứ 2 → 409 BRANCH_LIMIT_REACHED."""
    atok = await _admin_token(client, admin)
    await _create_tenant(client, atok, "p1-shop", "0903000001", "p1-123")
    otok = await _owner_login(client, "0903000001", "p1-123", "p1-shop")
    r = await _branch(client, otok, "CN2")
    assert r.status_code == 409
    assert r.json()["code"] == "BRANCH_LIMIT_REACHED"


async def test_plan3_allows_three_then_blocks(client: AsyncClient, admin: dict):
    """Gói 3 (max 3): có B1, thêm B2/B3 OK; B4 → 409."""
    atok = await _admin_token(client, admin)
    t = await _create_tenant(client, atok, "p3-shop", "0903000002", "p3-123")
    goi3 = next(p for p in await _plans(client, atok) if p["max_branches"] == 3)
    rs = await client.put(
        f"{TENANTS}/{t['tenant_id']}/subscription",
        json={"plan_id": goi3["id"]}, headers=auth_headers(atok),
    )
    assert rs.status_code == 200 and rs.json()["effective_max_branches"] == 3

    otok = await _owner_login(client, "0903000002", "p3-123", "p3-shop")
    assert (await _branch(client, otok, "B2")).status_code == 201
    assert (await _branch(client, otok, "B3")).status_code == 201
    r4 = await _branch(client, otok, "B4")
    assert r4.status_code == 409 and r4.json()["code"] == "BRANCH_LIMIT_REACHED"


async def test_no_subscription_blocks(client: AsyncClient):
    """⭐ KHÔNG subscription → tạo CN → 409 NO_SUBSCRIPTION (CHẶN, không unlimited)."""
    async with SessionFactory() as db:
        tenant = Tenant(name="No Sub", slug="no-sub", status="active")
        db.add(tenant)
        await db.flush()
        db.add(User(
            tenant_id=tenant.id, branch_id=None, role="owner", full_name="O",
            phone="0903000003", password_hash=hash_password("ns-123"), status="active",
        ))
        await db.commit()
    otok = await _owner_login(client, "0903000003", "ns-123", "no-sub")
    r = await _branch(client, otok, "CN A")
    assert r.status_code == 409
    assert r.json()["code"] == "NO_SUBSCRIPTION"


async def test_custom_max_branches_override(client: AsyncClient, admin: dict):
    """custom_max_branches=5 (gói 3) → tới 5 CN OK, CN thứ 6 → 409."""
    atok = await _admin_token(client, admin)
    t = await _create_tenant(client, atok, "custom-shop", "0903000004", "cs-123")
    goi3 = next(p for p in await _plans(client, atok) if p["max_branches"] == 3)
    rs = await client.put(
        f"{TENANTS}/{t['tenant_id']}/subscription",
        json={"plan_id": goi3["id"], "custom_max_branches": 5}, headers=auth_headers(atok),
    )
    assert rs.status_code == 200 and rs.json()["effective_max_branches"] == 5

    otok = await _owner_login(client, "0903000004", "cs-123", "custom-shop")
    for i in (2, 3, 4, 5):
        assert (await _branch(client, otok, f"B{i}")).status_code == 201, i
    r6 = await _branch(client, otok, "B6")
    assert r6.status_code == 409 and r6.json()["code"] == "BRANCH_LIMIT_REACHED"


async def test_active_count_excludes_soft_deleted(client: AsyncClient, admin: dict):
    """⭐ Đếm ACTIVE: gói 1, có B1, XÓA B1 (inactive) → tạo CN mới lại được."""
    atok = await _admin_token(client, admin)
    await _create_tenant(client, atok, "active-shop", "0903000005", "as-123")
    otok = await _owner_login(client, "0903000005", "as-123", "active-shop")

    # gói 1 đã đầy (B1 active) → B2 chặn.
    assert (await _branch(client, otok, "CN2")).status_code == 409

    # xóa B1 → active=0.
    bid = (await client.get(BRANCHES, headers=auth_headers(otok))).json()["items"][0]["id"]
    rdel = await client.delete(f"{BRANCHES}/{bid}", headers=auth_headers(otok))
    assert rdel.status_code == 200, rdel.text

    # tạo CN mới lại được (active 0 < 1).
    r = await _branch(client, otok, "CN mới")
    assert r.status_code == 201, r.text


# ── create_tenant gán Gói 1 ──────────────────────────────────────────────────
async def test_new_tenant_has_default_plan(client: AsyncClient, admin: dict):
    """⭐ Tenant mới CÓ subscription Gói 1 ngay: B1 tạo được; CN thứ 2 → 409 (KHÔNG
    NO_SUBSCRIPTION → chứng minh đã gán gói)."""
    atok = await _admin_token(client, admin)
    await _create_tenant(client, atok, "default-plan", "0903000006", "dp-123")
    otok = await _owner_login(client, "0903000006", "dp-123", "default-plan")
    r2 = await _branch(client, otok, "CN2")
    assert r2.status_code == 409
    assert r2.json()["code"] == "BRANCH_LIMIT_REACHED"


# ── gán gói (admin) ───────────────────────────────────────────────────────────
async def test_list_plans(client: AsyncClient, admin: dict):
    atok = await _admin_token(client, admin)
    plans = await _plans(client, atok)
    maxes = sorted(p["max_branches"] for p in plans)
    assert 1 in maxes and 3 in maxes


async def test_set_subscription_upsert(client: AsyncClient, admin: dict):
    """Gán gói 2 lần (đổi gói) → vẫn 1 subscription (UNIQUE tenant_id)."""
    atok = await _admin_token(client, admin)
    t = await _create_tenant(client, atok, "upsert-shop", "0903000007", "up-123")
    plans = await _plans(client, atok)
    await client.put(
        f"{TENANTS}/{t['tenant_id']}/subscription",
        json={"plan_id": plans[0]["id"]}, headers=auth_headers(atok),
    )
    await client.put(
        f"{TENANTS}/{t['tenant_id']}/subscription",
        json={"plan_id": plans[-1]["id"]}, headers=auth_headers(atok),
    )
    async with SessionFactory() as db:
        cnt = await db.scalar(
            select(func.count()).select_from(Subscription).where(
                Subscription.tenant_id == uuid.UUID(t["tenant_id"])
            )
        )
    assert cnt == 1


async def test_plans_endpoints_require_admin(client: AsyncClient, owner: dict):
    utok = await login(client, owner["phone"], owner["password"])
    r1 = await client.get(PLANS, headers=auth_headers(utok))
    r2 = await client.put(
        f"{TENANTS}/{uuid.uuid4()}/subscription",
        json={"plan_id": str(uuid.uuid4())}, headers=auth_headers(utok),
    )
    assert r1.status_code == 401 and r1.json()["code"] == "INVALID_TOKEN"
    assert r2.status_code == 401 and r2.json()["code"] == "INVALID_TOKEN"
