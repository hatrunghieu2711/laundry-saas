"""Test A2: admin tạo tenant mới (tiệm + CN B1 + owner + settings) trong 1 TRANSACTION.

Tâm điểm sống còn:
- Atomic: slug trùng → 409 + ROLLBACK SẠCH (không tenant/branch/user mồ côi).
- Insert bảng con (branch/user/settings strict RLS) xuyên RLS nhờ set_config GUC
  (admin GUC rỗng). Test RLS THẬT chạy bằng role laundry_app (non-bypass).
- owner login được bằng temp_password qua luồng user thường + slug mới.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SessionFactory, _AppSyncSession
from app.core.security import hash_password
from app.models.admin import Admin
from app.models.branch import Branch
from app.models.tenant import Tenant
from app.models.tenant_settings import TenantSettings
from app.models.user import User
from tests.conftest import login

ADMIN_LOGIN = "/api/v1/admin/auth/login"
CREATE_TENANT = "/api/v1/admin/tenants"
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


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _admin_token(client: AsyncClient, admin: dict) -> str:
    resp = await client.post(
        ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


def _payload(**over) -> dict:
    base = {
        "name": "Tiệm Mới",
        "slug": "tiem-moi",
        "owner_full_name": "Chủ Tiệm Mới",
        "owner_phone": "0900100100",
    }
    base.update(over)
    return base


# ── ⭐ tạo tenant đầy đủ trong 1 transaction ────────────────────────────────
async def test_create_tenant_full(client: AsyncClient, admin: dict):
    token = await _admin_token(client, admin)
    resp = await client.post(CREATE_TENANT, json=_payload(), headers=_bearer(token))
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["slug"] == "tiem-moi"
    assert body["owner_phone"] == "0900100100"
    assert body["branch_code"] == "B1"
    assert body["temp_password"]  # plaintext hiện 1 lần
    tid = uuid.UUID(body["tenant_id"])

    # DB: tenant + 1 branch B1 + 1 owner + settings đều tồn tại.
    async with SessionFactory() as db:
        tenant = await db.get(Tenant, tid)
        assert tenant is not None and tenant.slug == "tiem-moi" and tenant.status == "active"

        branches = (
            await db.execute(select(Branch).where(Branch.tenant_id == tid))
        ).scalars().all()
        assert len(branches) == 1
        assert branches[0].code == "B1" and branches[0].order_prefix == "B1"

        owners = (
            await db.execute(
                select(User).where(User.tenant_id == tid, User.role == "owner")
            )
        ).scalars().all()
        assert len(owners) == 1
        assert owners[0].phone == "0900100100" and owners[0].branch_id is None

        assert await db.get(TenantSettings, tid) is not None

        # sequence order_code per-tenant (order_code_seq_{tenant_hex}_b1) đã tạo.
        seq = await db.scalar(
            text("SELECT 1 FROM pg_class WHERE relkind='S' AND relname=:n"),
            {"n": f"order_code_seq_{tid.hex}_b1"},
        )
        assert seq == 1


async def test_new_tenant_first_order_starts_at_one(client: AsyncClient, admin: dict):
    """⭐ Tenant MỚI (A2) → sequence riêng → đơn đầu = B1-00001 (không nhảy theo 2H)."""
    token = await _admin_token(client, admin)
    resp = await client.post(
        CREATE_TENANT,
        json=_payload(slug="first-order-shop", owner_phone="0900700700"),
        headers=_bearer(token),
    )
    assert resp.status_code == 201, resp.text
    pw = resp.json()["temp_password"]

    lo = await client.post(
        USER_LOGIN,
        json={"phone": "0900700700", "password": pw, "slug": "first-order-shop"},
    )
    assert lo.status_code == 200, lo.text
    utok = lo.json()["access_token"]

    # owner cần branch_id → lấy CN B1 vừa tạo.
    br = await client.get(BRANCHES, headers=_bearer(utok))
    assert br.status_code == 200, br.text
    bid = br.json()["items"][0]["id"]

    body = {
        "items": [{"service_name": "Giặt", "quantity": 1, "unit_price": 10000}],
        "pickup_at": (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat(),
        "branch_id": bid,
    }
    ro = await client.post("/api/v1/orders", json=body, headers=_bearer(utok))
    assert ro.status_code == 201, ro.text
    assert ro.json()["order_code"] == "B1-00001"


async def test_create_tenant_custom_branch_name(client: AsyncClient, admin: dict):
    token = await _admin_token(client, admin)
    resp = await client.post(
        CREATE_TENANT,
        json=_payload(branch_name="CN Quận 1", branch_address="123 Lê Lợi", branch_phone="02838"),
        headers=_bearer(token),
    )
    assert resp.status_code == 201, resp.text
    tid = uuid.UUID(resp.json()["tenant_id"])
    async with SessionFactory() as db:
        branch = (
            await db.execute(select(Branch).where(Branch.tenant_id == tid))
        ).scalar_one()
        assert branch.name == "CN Quận 1"
        assert branch.address == "123 Lê Lợi" and branch.phone == "02838"


# ── ⭐ owner login được bằng temp_password ──────────────────────────────────
async def test_owner_can_login_with_temp_password(client: AsyncClient, admin: dict):
    token = await _admin_token(client, admin)
    resp = await client.post(CREATE_TENANT, json=_payload(), headers=_bearer(token))
    assert resp.status_code == 201, resp.text
    temp_pw = resp.json()["temp_password"]

    login_resp = await client.post(
        USER_LOGIN,
        json={"phone": "0900100100", "password": temp_pw, "slug": "tiem-moi"},
    )
    assert login_resp.status_code == 200, login_resp.text
    assert login_resp.json()["access_token"]


async def test_owner_password_explicit_used(client: AsyncClient, admin: dict):
    """owner_password truyền vào → dùng đúng cái đó (không sinh ngẫu nhiên)."""
    token = await _admin_token(client, admin)
    resp = await client.post(
        CREATE_TENANT, json=_payload(owner_password="my-own-pass-9"), headers=_bearer(token)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["temp_password"] == "my-own-pass-9"
    login_resp = await client.post(
        USER_LOGIN,
        json={"phone": "0900100100", "password": "my-own-pass-9", "slug": "tiem-moi"},
    )
    assert login_resp.status_code == 200, login_resp.text


async def test_owner_password_random_when_omitted(client: AsyncClient, admin: dict):
    """Không truyền owner_password → sinh ngẫu nhiên, trả trong response + login được."""
    token = await _admin_token(client, admin)
    resp = await client.post(CREATE_TENANT, json=_payload(), headers=_bearer(token))
    assert resp.status_code == 201, resp.text
    pw = resp.json()["temp_password"]
    assert pw and len(pw) >= 8
    login_resp = await client.post(
        USER_LOGIN, json={"phone": "0900100100", "password": pw, "slug": "tiem-moi"}
    )
    assert login_resp.status_code == 200, login_resp.text


# ── ⭐ slug trùng → 409 SLUG_EXISTS + rollback sạch (pre-check, chưa insert gì) ──
async def test_slug_conflict_pre_check_clean(client: AsyncClient, admin: dict):
    token = await _admin_token(client, admin)
    r1 = await client.post(
        CREATE_TENANT, json=_payload(slug="dup-shop", owner_phone="0900200200"),
        headers=_bearer(token),
    )
    assert r1.status_code == 201, r1.text

    r2 = await client.post(
        CREATE_TENANT,
        json=_payload(slug="dup-shop", owner_phone="0900200201", name="Khác"),
        headers=_bearer(token),
    )
    assert r2.status_code == 409
    assert r2.json()["code"] == "SLUG_EXISTS"

    # rollback sạch: đúng 1 tenant slug dup-shop, owner 0900200201 KHÔNG mồ côi.
    async with SessionFactory() as db:
        assert await db.scalar(
            select(func.count()).select_from(Tenant).where(Tenant.slug == "dup-shop")
        ) == 1
        assert await db.scalar(
            select(func.count()).select_from(User).where(User.phone == "0900200201")
        ) == 0


# ── ⭐ rollback THẬT: pre-check bị qua mặt → IntegrityError ở flush → rollback sạch ──
async def test_integrity_conflict_rollback_clean(
    client: AsyncClient, admin: dict, monkeypatch
):
    token = await _admin_token(client, admin)
    r1 = await client.post(
        CREATE_TENANT, json=_payload(slug="race-shop", owner_phone="0900300300"),
        headers=_bearer(token),
    )
    assert r1.status_code == 201, r1.text

    # Ép pre-check trả None (mô phỏng race) → để INSERT chạm unique index → rollback.
    from app.services import admin_tenant_service

    async def _none(*a, **k):
        return None

    monkeypatch.setattr(
        admin_tenant_service.tenant_service, "get_tenant_by_slug", _none
    )
    r2 = await client.post(
        CREATE_TENANT,
        json=_payload(slug="race-shop", owner_phone="0900300301", name="Race2"),
        headers=_bearer(token),
    )
    assert r2.status_code == 409, r2.text

    # rollback sạch: vẫn 1 tenant race-shop, owner 0900300301 không tồn tại.
    async with SessionFactory() as db:
        assert await db.scalar(
            select(func.count()).select_from(Tenant).where(Tenant.slug == "race-shop")
        ) == 1
        assert await db.scalar(
            select(func.count()).select_from(User).where(User.phone == "0900300301")
        ) == 0


# ── slug validate ──────────────────────────────────────────────────────────
async def test_slug_normalized_lower_trim(client: AsyncClient, admin: dict):
    token = await _admin_token(client, admin)
    resp = await client.post(
        CREATE_TENANT, json=_payload(slug="  Tiem-HOA  "), headers=_bearer(token)
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["slug"] == "tiem-hoa"


async def test_slug_invalid_chars_422(client: AsyncClient, admin: dict):
    token = await _admin_token(client, admin)
    resp = await client.post(
        CREATE_TENANT, json=_payload(slug="tiem moi!"), headers=_bearer(token)
    )
    assert resp.status_code == 422, resp.text


# ── cách ly A1: user token KHÔNG gọi được endpoint admin ────────────────────
async def test_create_tenant_requires_admin(client: AsyncClient, owner: dict):
    """user token (type=access) gọi POST /admin/tenants → 401 (cách ly A1)."""
    utoken = await login(client, owner["phone"], owner["password"])
    resp = await client.post(CREATE_TENANT, json=_payload(), headers=_bearer(utoken))
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_TOKEN"


async def test_create_tenant_no_token(client: AsyncClient):
    resp = await client.post(CREATE_TENANT, json=_payload())
    assert resp.status_code == 401
    assert resp.json()["code"] == "NOT_AUTHENTICATED"


# ── isolation tầng app: owner tenant mới chỉ thấy CN của mình ───────────────
async def test_new_tenant_owner_sees_only_own_branch(client: AsyncClient, admin: dict):
    token = await _admin_token(client, admin)
    ra = await client.post(
        CREATE_TENANT, json=_payload(slug="shop-a", owner_phone="0900400400"),
        headers=_bearer(token),
    )
    rb = await client.post(
        CREATE_TENANT,
        json=_payload(slug="shop-b", owner_phone="0900500500", name="Shop B"),
        headers=_bearer(token),
    )
    assert ra.status_code == 201 and rb.status_code == 201
    pw_a = ra.json()["temp_password"]

    la = await client.post(
        USER_LOGIN, json={"phone": "0900400400", "password": pw_a, "slug": "shop-a"}
    )
    assert la.status_code == 200, la.text
    utok = la.json()["access_token"]

    br = await client.get(BRANCHES, headers=_bearer(utok))
    assert br.status_code == 200, br.text
    items = br.json()["items"]
    assert len(items) == 1
    assert items[0]["code"] == "B1"
    assert items[0]["tenant_id"] == ra.json()["tenant_id"]


# ── ⭐ RLS THẬT: create_tenant chạy bằng laundry_app (non-bypass) → set_config
#    là load-bearing. Nếu set_config hỏng, RLS chặn insert con → fail. ──────────
async def test_create_tenant_under_real_rls(app_role_engine):
    """Chạy service create_tenant bằng role laundry_app (RLS có hiệu lực).

    after_begin set GUC='' (ContextVar None) như request admin; set_config tường
    minh trong create_tenant nâng GUC = tenant.id → insert branch/user/settings
    (strict RLS WITH CHECK) PASS. Đây là bằng chứng set_config hoạt động xuyên RLS.
    """
    from app.schemas.admin import TenantCreate
    from app.services import admin_tenant_service

    factory = async_sessionmaker(
        bind=app_role_engine,
        class_=AsyncSession,
        sync_session_class=_AppSyncSession,
        expire_on_commit=False,
    )
    data = TenantCreate(
        name="RLS Shop", slug="rls-shop",
        owner_full_name="Owner RLS", owner_phone="0900600600",
    )
    async with factory() as db:
        result = await admin_tenant_service.create_tenant(db, data)
    assert result.slug == "rls-shop"

    # Đọc lại bằng OWNER (bypass) — xác nhận đã GHI THẬT đủ tenant+branch+owner+settings.
    async with SessionFactory() as s:
        tenant = (
            await s.execute(select(Tenant).where(Tenant.slug == "rls-shop"))
        ).scalar_one()
        assert await s.scalar(
            select(func.count()).select_from(Branch).where(Branch.tenant_id == tenant.id)
        ) == 1
        assert await s.scalar(
            select(func.count()).select_from(User).where(
                User.tenant_id == tenant.id, User.role == "owner"
            )
        ) == 1
        assert await s.get(TenantSettings, tenant.id) is not None
