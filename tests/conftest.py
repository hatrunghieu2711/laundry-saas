"""Fixtures dùng chung cho test.

LƯỚI AN TOÀN — test PHẢI chạy trên DATABASE RIÊNG (tên kết thúc '_test'):
- conftest trỏ DATABASE_URL sang DB test TRƯỚC khi import app (engine build 1 lần
  trên DB test), tự tạo DB test nếu chưa có và chạy migration lên đó.
- Mọi TRUNCATE/teardown đều ASSERT chỉ thực thi trên DB '_test'. TUYỆT ĐỐI không
  đụng DB sản xuất (vd 'laundry'). Nếu URL không phải '_test' → raise, dừng ngay.
"""
import asyncio
import os
import subprocess
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest  # noqa: F401
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ── Phân giải URL DB test (TRƯỚC khi import app) ──────────────────────────────
def _derive_test_url() -> str:
    """URL DB test:
    - TEST_DATABASE_URL set → dùng NGUYÊN VĂN (không tự sửa). Safety check bên dưới
      sẽ ASSERT tên '_test'; nếu lỡ trỏ DB sản xuất → raise, KHÔNG đụng DB đó.
    - Không set → suy ra bằng cách đổi tên db thành '<db>_test'.

    ⚠️ RLS R1/R2: ƯU TIÊN MIGRATION_DATABASE_URL (user OWNER `laundry`) làm gốc, vì
    DATABASE_URL nay có thể là `laundry_app` (non-owner) — không migrate được và CHƯA
    có grant trên DB test → test phải chạy bằng OWNER. (RLS isolation chạy bằng role
    app sẽ dựng engine riêng ở R3, không đụng harness chung này.)
    """
    explicit = os.environ.get("TEST_DATABASE_URL")
    if explicit:
        return explicit
    base = os.environ.get("MIGRATION_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not base:
        raise RuntimeError(
            "Cần TEST_DATABASE_URL / MIGRATION_DATABASE_URL / DATABASE_URL để chạy test"
        )
    url = make_url(base)
    db = url.database or ""
    if db.endswith("_test"):
        return base
    return url.set(database=f"{db}_test").render_as_string(hide_password=False)


_TEST_URL = _derive_test_url()
_TEST_DB_NAME = make_url(_TEST_URL).database or ""

# SAFETY CHECK: từ chối chạy nếu DB không kết thúc '_test' (chống xóa nhầm DB thật).
if not _TEST_DB_NAME.endswith("_test"):
    raise RuntimeError(
        f"AN TOÀN: database test phải kết thúc bằng '_test' (nhận '{_TEST_DB_NAME}'). "
        "Dừng để tránh TRUNCATE nhầm database sản xuất."
    )


# DSN role-app (laundry_app, non-bypass) trên DB test — cho test RLS CÁCH LY (R3).
# Lấy TỪ DATABASE_URL gốc (app connect laundry_app) TRƯỚC khi bị overwrite; swap db→_test.
# None nếu không có (vd CI chỉ có owner) → test RLS sẽ skip thay vì fail.
def _derive_app_role_test_url() -> str | None:
    raw = os.environ.get("APP_ROLE_DATABASE_URL") or os.environ.get("DATABASE_URL")
    if not raw:
        return None
    u = make_url(raw)
    db = u.database or ""
    if not db.endswith("_test"):
        u = u.set(database=f"{db}_test")
    if not (u.database or "").endswith("_test"):
        return None
    return u.render_as_string(hide_password=False)


_APP_ROLE_TEST_URL = _derive_app_role_test_url()

# Trỏ app + alembic sang DB test TRƯỚC khi import app.core.* (engine build 1 lần).
os.environ["DATABASE_URL"] = _TEST_URL
# ⚠️ CHỐT AN TOÀN (RLS R1): alembic/env.py nay ƯU TIÊN MIGRATION_DATABASE_URL. Nếu biến này
# tồn tại trong môi trường (vd .env prod trỏ user owner `laundry`) mà test KHÔNG override →
# `alembic upgrade head` của test sẽ migrate NHẦM vào DB PROD. Ép nó về DB `_test` (đã được
# SAFETY CHECK ở trên xác nhận tên kết thúc '_test') → test KHÔNG BAO GIỜ chạm prod.
os.environ["MIGRATION_DATABASE_URL"] = _TEST_URL

from app.core.config import get_settings  # noqa: E402

get_settings.cache_clear()  # bỏ cache phòng khi URL cũ đã được đọc

from app.core.database import SessionFactory, engine  # noqa: E402
from app.core.redis import redis_client  # noqa: E402
from app.core.security import hash_password  # noqa: E402
from app.main import app  # noqa: E402
from app.models.billing import Plan, Subscription  # noqa: E402
from app.models.tenant import Tenant  # noqa: E402
from app.models.user import User  # noqa: E402


async def _ensure_test_db() -> None:
    """Tạo database test nếu chưa có — kết nối DB bảo trì 'postgres', AUTOCOMMIT
    (CREATE DATABASE không chạy trong transaction)."""
    admin_url = make_url(_TEST_URL).set(database="postgres")
    admin = create_async_engine(admin_url, isolation_level="AUTOCOMMIT")
    try:
        async with admin.connect() as conn:
            exists = await conn.scalar(
                text("SELECT 1 FROM pg_database WHERE datname = :n"),
                {"n": _TEST_DB_NAME},
            )
            if not exists:
                await conn.execute(text(f'CREATE DATABASE "{_TEST_DB_NAME}"'))
    finally:
        await admin.dispose()


def _provision_test_db() -> None:
    """Tạo DB test + migrate lên head (idempotent, mỗi session một lần).

    alembic env.py đọc MIGRATION_DATABASE_URL (đã ép về DB test ở trên) nên migrate
    đúng DB test — cùng một migration chạy được trên cả DB sản xuất lẫn DB test."""
    asyncio.run(_ensure_test_db())
    subprocess.run(
        ["alembic", "upgrade", "head"],
        check=True,
        cwd=_PROJECT_ROOT,
        env=os.environ.copy(),
    )


_provision_test_db()

# Test client chạy qua http:// — tắt cookie Secure để httpx giữ/gửi cookie.
get_settings().cookie_secure = False

# Các bảng test chạm tới — dọn giữa mỗi test (CASCADE lo FK).
# admins: NGOÀI RLS, không FK — dọn để test admin (Stage A1) idempotent giữa các test.
_CLEAN_TABLES = (
    "discount_logs, cash_transactions, payments, order_items, orders, price_rules, "
    "service_tiers, services, categories, shifts, refresh_tokens, users, branches, "
    "customers, tenant_settings, tenants, admins"
)


def auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


async def _assign_test_subscription(db, tenant_id) -> None:
    """Plans-1: gán subscription RỘNG (custom_max=99) cho tenant test → tạo branch
    không vướng giới hạn gói. Plan tham chiếu lấy từ seed (migration). Tenant test
    chuyên kiểm gói tự gán sub riêng (vd qua create_tenant/set_subscription)."""
    plan = (await db.execute(select(Plan).limit(1))).scalar_one_or_none()
    if plan is not None:
        db.add(
            Subscription(
                tenant_id=tenant_id, plan_id=plan.id,
                custom_max_branches=99, status="active",
            )
        )


# Registry phone→slug do owner/owner2 fixture điền — để login() TỰ kèm slug khi
# môi trường có >1 tenant (GĐ2 siết slug bắt buộc). Test body không phải sửa.
_SLUG_BY_PHONE: dict[str, str] = {}


async def login(
    client: AsyncClient, phone: str, password: str, slug: str | None = None
) -> str:
    """Đăng nhập, trả access_token (raise nếu fail).

    slug None → tự tra registry (owner/owner2). Có >1 tenant active mà thiếu slug,
    BE sẽ 400 SLUG_REQUIRED; helper tự kèm slug đã biết để lấy token đúng tenant.
    """
    if slug is None:
        slug = _SLUG_BY_PHONE.get(phone)
    body = {"phone": phone, "password": password}
    if slug:
        body["slug"] = slug
    resp = await client.post("/api/v1/auth/login", json=body)
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# Drop các sequence order_code_seq_* do tạo branch sinh ra — TRUNCATE không reset
# sequence nên phải drop để mỗi test bắt đầu order_code lại từ 00001.
_DROP_ORDER_SEQS = """
DO $$
DECLARE s text;
BEGIN
  FOR s IN SELECT relname FROM pg_class
           WHERE relkind = 'S' AND relname LIKE 'order_code_seq_%'
  LOOP EXECUTE 'DROP SEQUENCE IF EXISTS ' || quote_ident(s); END LOOP;
END $$;
"""


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Dọn DB trước test; dispose engine sau test để pool gắn đúng event loop."""
    # LƯỚI AN TOÀN cuối: chỉ TRUNCATE trên DB '_test'. Nếu engine lỡ trỏ DB khác
    # (cấu hình sai) → dừng NGAY, KHÔNG xóa gì — tránh phá DB sản xuất.
    db_name = engine.url.database or ""
    assert db_name.endswith("_test"), (
        f"AN TOÀN: từ chối TRUNCATE trên DB '{db_name}' (không kết thúc bằng '_test')."
    )
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_CLEAN_TABLES} CASCADE"))
        await conn.execute(text(_DROP_ORDER_SEQS))
    yield
    await engine.dispose()
    # Redis client singleton (rate limit) gắn vào event loop lần dùng đầu; mỗi test
    # chạy loop riêng → ngắt pool để test sau tạo kết nối mới trên loop của nó.
    try:
        await redis_client.connection_pool.disconnect()
    except Exception:
        pass


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest_asyncio.fixture
async def app_role_engine():
    """Engine connect bằng `laundry_app` (NON-bypass) trên DB test — test RLS CÁCH LY (R3).

    Harness chung chạy bằng OWNER (bypass RLS). Để nghiệm thu RLS THẬT phải connect
    bằng role app (bị policy chặn). Fixture: cấp quyền cho laundry_app trên DB test
    (R1 chưa chạy trên laundry_test) RỒI tạo engine role app. SKIP nếu không có DSN
    role-app / role không kết nối được / role vẫn bypass (cấu hình sai)."""
    if not _APP_ROLE_TEST_URL:
        pytest.skip("Không có DSN role-app (laundry_app) cho test RLS cách ly")

    # Cấp quyền cho laundry_app trên DB test (chạy bằng owner). Idempotent.
    async with engine.begin() as conn:
        await conn.execute(text(f'GRANT CONNECT ON DATABASE "{_TEST_DB_NAME}" TO laundry_app'))
        await conn.execute(text("GRANT USAGE ON SCHEMA public TO laundry_app"))
        await conn.execute(
            text("GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO laundry_app")
        )
        await conn.execute(
            text("GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO laundry_app")
        )

    app_engine = create_async_engine(_APP_ROLE_TEST_URL)
    try:
        async with app_engine.connect() as c:
            bypass = await c.scalar(
                text("SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user")
            )
        if bypass is not False:
            await app_engine.dispose()
            pytest.skip("Role app không tồn tại / vẫn BYPASSRLS — bỏ qua test cách ly")
    except Exception as exc:  # không kết nối được (sai pw / role thiếu)
        await app_engine.dispose()
        pytest.skip(f"Không kết nối được role app cho test RLS: {exc}")

    try:
        yield app_engine
    finally:
        await app_engine.dispose()


@pytest_asyncio.fixture
async def owner():
    """Tạo 1 tenant + 1 owner active. Trả thông tin đăng nhập."""
    password = "owner123"
    async with SessionFactory() as db:
        tenant = Tenant(name="Giặt Ủi 2H", slug="giat-ui-2h", status="active")
        db.add(tenant)
        await db.flush()
        user = User(
            tenant_id=tenant.id,
            branch_id=None,
            role="owner",
            full_name="Chủ Giặt Ủi 2H",
            phone="0900000001",
            password_hash=hash_password(password),
            status="active",
        )
        db.add(user)
        await _assign_test_subscription(db, tenant.id)  # Plans-1: tenant test có gói
        await db.commit()
        _SLUG_BY_PHONE[user.phone] = tenant.slug  # để login() tự kèm slug (GĐ2)
        return {
            "user_id": user.id,
            "tenant_id": tenant.id,
            "phone": user.phone,
            "password": password,
            "role": user.role,
            "slug": tenant.slug,
        }


@pytest_asyncio.fixture
async def owner2():
    """Tenant + owner THỨ HAI — để verify cách ly dữ liệu giữa các tenant."""
    password = "owner456"
    async with SessionFactory() as db:
        tenant = Tenant(name="Sạch Thơm", slug="sach-thom", status="active")
        db.add(tenant)
        await db.flush()
        user = User(
            tenant_id=tenant.id,
            branch_id=None,
            role="owner",
            full_name="Chủ Sạch Thơm",
            phone="0911000001",
            password_hash=hash_password(password),
            status="active",
        )
        db.add(user)
        await _assign_test_subscription(db, tenant.id)  # Plans-1: tenant test có gói
        await db.commit()
        _SLUG_BY_PHONE[user.phone] = tenant.slug  # để login() tự kèm slug (GĐ2)
        return {
            "user_id": user.id,
            "tenant_id": tenant.id,
            "phone": user.phone,
            "password": password,
            "role": user.role,
            "slug": tenant.slug,
        }


def make_expired_access_token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """JWT access token đã hết hạn — để test nhánh TOKEN_EXPIRED."""
    s = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": "owner",
        "branch_id": None,
        "type": "access",
        "iat": now - timedelta(hours=2),
        "exp": now - timedelta(hours=1),
    }
    return jwt.encode(payload, s.jwt_secret, algorithm=s.jwt_algorithm)
