"""Test auth ADMIN (Super Admin) — TÁCH HẲN auth user. Stage A1.

Bao: login đúng/sai (cùng 401 generic), cách ly token 2 CHIỀU (admin↔user),
/admin/me KHÔNG vướng db.get(User), get_current_admin KHÔNG set tenant GUC,
bootstrap idempotent.
"""
import jwt
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import func, select

from app.core.config import get_settings
from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.admin import Admin
from tests.conftest import login

ADMIN_LOGIN = "/api/v1/admin/auth/login"
ADMIN_ME = "/api/v1/admin/me"
ORDERS = "/api/v1/orders"  # endpoint owner (require_role) — dùng test cách ly


@pytest_asyncio.fixture
async def admin() -> dict:
    """Tạo 1 super_admin active (ngoài tenant). Trả thông tin đăng nhập."""
    password = "admin-secret-123"
    async with SessionFactory() as db:
        a = Admin(
            phone="0999999999",
            full_name="Super Admin",
            role="super_admin",
            password_hash=hash_password(password),
            status="active",
        )
        db.add(a)
        await db.commit()
        return {"id": a.id, "phone": a.phone, "password": password, "role": a.role}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _admin_login(client: AsyncClient, admin: dict) -> str:
    resp = await client.post(
        ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]}
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["access_token"]


# ── login ────────────────────────────────────────────────────────────────
async def test_admin_login_success_token_shape(client: AsyncClient, admin: dict):
    """⭐ admin login đúng → token type='admin_access', sub=admin_id, KHÔNG tenant_id."""
    resp = await client.post(
        ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]}
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    token = body["access_token"]
    assert token
    # A1 access-token only: KHÔNG cookie/refresh.
    assert "refresh_token" not in resp.cookies

    s = get_settings()
    payload = jwt.decode(token, s.jwt_secret, algorithms=[s.jwt_algorithm])
    assert payload["type"] == "admin_access"
    assert payload["sub"] == str(admin["id"])
    assert "tenant_id" not in payload
    assert "branch_id" not in payload


async def test_admin_login_wrong_password(client: AsyncClient, admin: dict):
    resp = await client.post(
        ADMIN_LOGIN, json={"phone": admin["phone"], "password": "sai-mat-khau"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


async def test_admin_login_unknown_phone(client: AsyncClient, admin: dict):
    """phone không tồn tại → cùng 401 generic (không lộ phone tồn tại)."""
    resp = await client.post(
        ADMIN_LOGIN, json={"phone": "0000000000", "password": "admin-secret-123"}
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


# ── /admin/me ──────────────────────────────────────────────────────────────
async def test_admin_me_returns_admin_info(client: AsyncClient, admin: dict):
    """GET /admin/me với admin token → trả admin info, KHÔNG vướng db.get(User)."""
    token = await _admin_login(client, admin)
    resp = await client.get(ADMIN_ME, headers=_bearer(token))
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["id"] == str(admin["id"])
    assert body["phone"] == admin["phone"]
    assert body["full_name"] == "Super Admin"
    assert body["role"] == "super_admin"


async def test_admin_me_no_token(client: AsyncClient, admin: dict):
    resp = await client.get(ADMIN_ME)
    assert resp.status_code == 401
    assert resp.json()["code"] == "NOT_AUTHENTICATED"


# ── cách ly token 2 CHIỀU ───────────────────────────────────────────────────
async def test_admin_token_rejected_on_user_endpoint(client: AsyncClient, admin: dict):
    """⭐ admin token gọi endpoint owner (GET /orders) → 401 (type != 'access')."""
    token = await _admin_login(client, admin)
    resp = await client.get(ORDERS, headers=_bearer(token))
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_TOKEN"


async def test_user_token_rejected_on_admin_endpoint(client: AsyncClient, owner: dict):
    """⭐ user token gọi GET /admin/me → 401 (type != 'admin_access')."""
    token = await login(client, owner["phone"], owner["password"])
    resp = await client.get(ADMIN_ME, headers=_bearer(token))
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_TOKEN"


# ── GUC rỗng cho admin (KHÔNG set tenant context) ───────────────────────────
async def test_get_current_admin_does_not_set_tenant_guc(admin: dict):
    """⭐ get_current_admin KHÔNG gọi set_current_tenant → GUC vẫn rỗng (None).

    Admin không đọc dữ liệu tenant: nếu lỡ query bảng tenant thì GUC '' → RLS chặn
    (thấy 0 dòng). A1 chưa có endpoint đó; ở đây xác nhận trực tiếp GUC rỗng.
    """
    from app.api.deps import get_current_admin
    from app.core.tenant_ctx import get_current_tenant, reset_current_tenant
    from app.services.admin_auth_service import issue_admin_session

    reset_current_tenant()
    async with SessionFactory() as db:
        a = await db.get(Admin, admin["id"])
        token = issue_admin_session(a).access_token
        resolved = await get_current_admin(db, authorization=f"Bearer {token}")
        assert resolved.id == admin["id"]
    # get_current_admin KHÔNG set tenant → ContextVar vẫn ở default None.
    assert get_current_tenant() is None


# ── bootstrap admin #1 ──────────────────────────────────────────────────────
async def test_bootstrap_admin_idempotent(monkeypatch):
    """bootstrap chạy 2 lần KHÔNG tạo trùng (idempotent theo phone)."""
    from scripts.bootstrap_admin import bootstrap

    monkeypatch.setenv("SUPERADMIN_PHONE", "0900111222")
    monkeypatch.setenv("SUPERADMIN_PASSWORD", "boot-secret-123")
    monkeypatch.setenv("SUPERADMIN_NAME", "Boot Admin")

    await bootstrap()
    await bootstrap()  # lần 2: phát hiện đã có → bỏ qua

    async with SessionFactory() as db:
        count = await db.scalar(
            select(func.count()).select_from(Admin).where(Admin.phone == "0900111222")
        )
    assert count == 1


async def test_bootstrap_admin_then_login(client: AsyncClient, monkeypatch):
    """admin tạo bằng bootstrap → đăng nhập được qua /admin/auth/login."""
    from scripts.bootstrap_admin import bootstrap

    monkeypatch.setenv("SUPERADMIN_PHONE", "0900333444")
    monkeypatch.setenv("SUPERADMIN_PASSWORD", "boot-login-123")
    await bootstrap()

    resp = await client.post(
        ADMIN_LOGIN, json={"phone": "0900333444", "password": "boot-login-123"}
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["access_token"]
