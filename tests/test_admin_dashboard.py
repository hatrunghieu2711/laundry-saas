"""Dashboard Super Admin — đếm XUYÊN TENANT dưới RLS THẬT + biên ngày VN.

⚠️ orders/branches STRICT RLS → get_dashboard LOOP set_config per tenant rồi cộng. Phải
chạy app_role_engine (laundry_app NON-BYPASS) — owner-harness (bypass) CHE lỗi RLS:
thiếu loop → RLS trả 0. Biên "hôm nay" theo GIỜ VN (UTC+7), không UTC.
"""
from datetime import datetime, time, timedelta, timezone

import pytest_asyncio
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SessionFactory, _AppSyncSession, get_db
from app.core.security import hash_password
from app.main import app
from app.models.admin import Admin
from app.models.billing import Plan, Subscription
from app.models.tenant import Tenant
from app.models.user import User
from app.services.price_rule_service import vn_today
from tests.conftest import auth_headers

DASHBOARD = "/api/v1/admin/dashboard"
ADMIN_LOGIN = "/api/v1/admin/auth/login"
_VN_TZ = timezone(timedelta(hours=7))


@pytest_asyncio.fixture
async def rls_db(app_role_engine):
    """Override get_db → session bind laundry_app (RLS thật) + event GUC after_begin."""
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


async def _seed_admin(phone: str) -> dict:
    async with SessionFactory() as db:
        db.add(Admin(
            phone=phone, full_name="SA", role="super_admin",
            password_hash=hash_password("admin-pw-123"), status="active",
        ))
        await db.commit()
    return {"phone": phone, "password": "admin-pw-123"}


async def _seed_tenant(slug, owner_phone, *, order_times=(), expires_at=None):
    """Tenant active + owner active + 1 CN active + subscription; orders tại order_times
    (UTC tz-aware). Seed bằng OWNER (bypass) — không phụ thuộc GUC."""
    async with SessionFactory() as db:
        tenant = Tenant(name=f"Shop {slug}", slug=slug, status="active")
        db.add(tenant)
        await db.flush()
        plan = (await db.execute(select(Plan).order_by(Plan.max_branches))).scalars().first()
        db.add(Subscription(
            tenant_id=tenant.id, plan_id=plan.id, status="active",
            current_period_end=expires_at,
        ))
        owner = User(
            tenant_id=tenant.id, branch_id=None, role="owner", full_name="O",
            phone=owner_phone, password_hash=hash_password("pw123x"), status="active",
        )
        db.add(owner)
        await db.flush()
        bid = await db.scalar(
            text(
                "INSERT INTO branches (id, tenant_id, name, code, order_prefix, status) "
                "VALUES (gen_random_uuid(), :t, 'CN', 'B1', 'B1', 'active') RETURNING id"
            ),
            {"t": str(tenant.id)},
        )
        for i, ca in enumerate(order_times):
            await db.execute(
                text(
                    "INSERT INTO orders "
                    "(id, tenant_id, branch_id, order_code, pickup_at, created_by, created_at) "
                    "VALUES (gen_random_uuid(), :t, :b, :oc, now(), :u, :ca)"
                ),
                {"t": str(tenant.id), "b": str(bid), "oc": f"{slug}-{i}",
                 "u": str(owner.id), "ca": ca},
            )
        await db.commit()
    return tenant.id


async def _atok(client, admin) -> str:
    r = await client.post(ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


# ── ⭐ Loop đếm cross-tenant + biên ngày VN ──────────────────────────────────
async def test_dashboard_counts_cross_tenant_and_vn_boundary(client, rls_db):
    admin = await _seed_admin("0997700001")
    start_today = datetime.combine(vn_today(), time.min, tzinfo=_VN_TZ)
    today_am = start_today + timedelta(minutes=30)  # 00:30 VN hôm nay (= UTC hôm qua) → vẫn "hôm nay"
    old = start_today - timedelta(days=5)           # rõ ràng KHÔNG phải hôm nay
    await _seed_tenant("dash-a", "0905500001", order_times=(today_am, old))
    await _seed_tenant("dash-b", "0905500002", order_times=(today_am,))

    d = (await client.get(DASHBOARD, headers=auth_headers(await _atok(client, admin)))).json()
    # 2 đơn sáng nay (mỗi tenant 1) — thiếu loop → RLS 0; sai TZ (UTC-midnight) → 0.
    assert d["orders_today"] == 2
    assert d["orders_month"] >= 2
    assert d["branches_active"] == 2           # 1 CN active / tenant
    assert d["users_active"] >= 2              # 2 owner active
    assert d["tenants_by_status"].get("active", 0) >= 2


# ── Tenant cần chú ý (warning + grace + expired) + recent + status ───────────
async def test_dashboard_expiring_and_recent(client, rls_db):
    admin = await _seed_admin("0997700002")
    now = datetime.now(timezone.utc)
    await _seed_tenant("exp-warn", "0905500003", expires_at=now + timedelta(days=2))    # warning
    await _seed_tenant("exp-grace", "0905500004", expires_at=now - timedelta(days=1))   # grace (GRACE=3)
    await _seed_tenant("exp-past", "0905500005", expires_at=now - timedelta(days=10))   # expired
    await _seed_tenant("exp-none", "0905500006")                                        # vô hạn → KHÔNG

    d = (await client.get(DASHBOARD, headers=auth_headers(await _atok(client, admin)))).json()
    by_slug = {e["slug"]: e for e in d["expiring"]}
    assert by_slug["exp-warn"]["expiry_status"] == "warning"
    assert by_slug["exp-grace"]["expiry_status"] == "grace"
    assert by_slug["exp-past"]["expiry_status"] == "expired"
    assert "exp-none" not in by_slug                    # vô hạn không cảnh báo
    # recent_tenants: tenant mới tạo có mặt
    assert any(t["slug"] == "exp-none" for t in d["recent_tenants"])
    assert d["tenants_by_status"].get("active", 0) >= 4


# ── reset GUC sau loop — request sau (đếm) không bị rò context tenant cuối ────
async def test_dashboard_resets_guc_after_loop(client, rls_db):
    admin = await _seed_admin("0997700003")
    await _seed_tenant("g-a", "0905500007")
    await _seed_tenant("g-b", "0905500008")
    atok = await _atok(client, admin)
    d1 = (await client.get(DASHBOARD, headers=auth_headers(atok))).json()
    d2 = (await client.get(DASHBOARD, headers=auth_headers(atok))).json()
    # users_active permissive-when-empty: cần GUC rỗng sau loop → 2 lần gọi BẰNG NHAU (không rò).
    assert d1["users_active"] == d2["users_active"] >= 2
    assert d1["tenants_by_status"] == d2["tenants_by_status"]
