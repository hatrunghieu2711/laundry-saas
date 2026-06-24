"""Regression bug 500 set_subscription dưới RLS THẬT (laundry_app non-bypass).

GỐC (Stage UI c5375c8): set_subscription re-read subscription_info SAU commit() → GUC
is_local reset khi commit → dưới laundry_app (RLS) subscriptions VÔ HÌNH (GUC admin rỗng)
→ plan None → SubscriptionOut 500. Vỡ MỌI lần lưu gói (cả đổi plan, không riêng expires_at).

⚠️ Owner-harness (bypass RLS) CHE lỗi này — phải chạy qua app_role_engine (role app, RLS
có hiệu lực) bằng cách override get_db sang session bind role + event GUC after_begin.
Skip nếu môi trường không có DSN role-app (xem fixture app_role_engine).
"""
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SessionFactory, _AppSyncSession, get_db
from app.core.security import hash_password
from app.main import app
from app.models.admin import Admin
from app.models.billing import Plan, Subscription
from app.models.tenant import Tenant
from tests.conftest import auth_headers

ADMIN_LOGIN = "/api/v1/admin/auth/login"
TENANTS = "/api/v1/admin/tenants"


@pytest_asyncio.fixture
async def rls_db(app_role_engine):
    """Override get_db → AsyncSession bind role laundry_app (RLS THẬT) + event GUC.

    sync_session_class=_AppSyncSession → after_begin set app.current_tenant_id từ
    ContextVar mỗi transaction (GIỐNG prod). Admin request → ContextVar rỗng → GUC ''
    → tái hiện đúng cảnh subscriptions vô hình sau commit."""
    role_sm = async_sessionmaker(
        bind=app_role_engine, class_=AsyncSession,
        sync_session_class=_AppSyncSession, expire_on_commit=False,
    )

    async def _role_get_db():
        async with role_sm() as s:
            yield s

    app.dependency_overrides[get_db] = _role_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


async def _seed(admin_phone: str, slug: str) -> dict:
    """Seed admin + tenant + subscription(plan) bằng OWNER (bypass RLS) — không phụ thuộc GUC."""
    async with SessionFactory() as db:
        admin = Admin(
            phone=admin_phone, full_name="SA", role="super_admin",
            password_hash=hash_password("admin-pw-123"), status="active",
        )
        db.add(admin)
        tenant = Tenant(name=f"Shop {slug}", slug=slug, status="active")
        db.add(tenant)
        await db.flush()
        plan = (await db.execute(select(Plan).order_by(Plan.max_branches))).scalars().first()
        db.add(Subscription(tenant_id=tenant.id, plan_id=plan.id, status="active"))
        await db.commit()
        return {
            "admin_phone": admin_phone, "admin_pw": "admin-pw-123",
            "tenant_id": str(tenant.id), "plan_id": str(plan.id), "plan_name": plan.name,
        }


async def _atok(client, s) -> str:
    r = await client.post(ADMIN_LOGIN, json={"phone": s["admin_phone"], "password": s["admin_pw"]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


async def _put(client, atok, tid, **body):
    return await client.put(f"{TENANTS}/{tid}/subscription", json=body, headers=auth_headers(atok))


# ── ⭐ set expires_at dưới RLS thật → 200 (KHÔNG 500), plan KHÔNG None ────────
async def test_set_expires_at_under_rls(client, rls_db):
    s = await _seed("0998800001", "wic-rls")
    atok = await _atok(client, s)
    exp = (datetime.now(timezone.utc) + timedelta(days=10)).isoformat()

    r = await _put(client, atok, s["tenant_id"], plan_id=s["plan_id"], expires_at=exp)
    assert r.status_code == 200, r.text  # bug cũ: 500 ResponseValidationError
    b = r.json()
    assert b["plan_id"] == s["plan_id"]                 # build-from-plan: đúng plan
    assert b["plan_name"] == s["plan_name"]
    assert b["effective_max_branches"] is not None
    assert b["expires_at"] is not None
    assert b["expiry_status"] == "active"               # 10 ngày > WARN=7
    assert b["days_left"] == 10


# ── ⭐ set CHỈ plan (không expires_at) dưới RLS thật → 200 (regression "lưu gói") ─
async def test_set_plan_only_under_rls(client, rls_db):
    s = await _seed("0998800002", "wic-rls2")
    atok = await _atok(client, s)
    r = await _put(client, atok, s["tenant_id"], plan_id=s["plan_id"])
    assert r.status_code == 200, r.text  # bug cũ: cả đổi plan cũng 500
    b = r.json()
    assert b["plan_id"] == s["plan_id"]
    assert b["plan_name"] == s["plan_name"]
    assert b["expires_at"] is None
    assert b["expiry_status"] == "active"


# ── set null expires_at → vô hạn, plan vẫn đúng ──────────────────────────────
async def test_set_null_expires_under_rls(client, rls_db):
    s = await _seed("0998800003", "wic-rls3")
    atok = await _atok(client, s)
    # đặt hạn rồi xóa hạn (None)
    await _put(client, atok, s["tenant_id"], plan_id=s["plan_id"],
               expires_at=(datetime.now(timezone.utc) - timedelta(days=1)).isoformat())
    r = await _put(client, atok, s["tenant_id"], plan_id=s["plan_id"], expires_at=None)
    assert r.status_code == 200, r.text
    b = r.json()
    assert b["expires_at"] is None
    assert b["expiry_status"] == "active"
    assert b["plan_id"] == s["plan_id"]


# ── set custom_max → effective = custom (build-from-plan đúng) ────────────────
async def test_set_custom_max_under_rls(client, rls_db):
    s = await _seed("0998800004", "wic-rls4")
    atok = await _atok(client, s)
    r = await _put(client, atok, s["tenant_id"], plan_id=s["plan_id"], custom_max_branches=9)
    assert r.status_code == 200, r.text
    assert r.json()["effective_max_branches"] == 9
    assert r.json()["custom_max_branches"] == 9
