"""Fixtures dùng chung cho test (chạy trong app container, DB postgres thật)."""
import uuid
from datetime import datetime, timedelta, timezone

import jwt
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text

from app.core.config import get_settings
from app.core.database import SessionFactory, engine
from app.core.security import hash_password
from app.main import app
from app.models.tenant import Tenant
from app.models.user import User

# Test client chạy qua http:// — tắt cookie Secure để httpx giữ/gửi cookie.
get_settings().cookie_secure = False

# Các bảng auth động chạm tới — dọn giữa mỗi test.
_CLEAN_TABLES = "refresh_tokens, users, tenants"


@pytest_asyncio.fixture(autouse=True)
async def clean_db():
    """Dọn DB trước test; dispose engine sau test để pool gắn đúng event loop."""
    async with engine.begin() as conn:
        await conn.execute(text(f"TRUNCATE {_CLEAN_TABLES} CASCADE"))
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


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
        await db.commit()
        return {
            "user_id": user.id,
            "tenant_id": tenant.id,
            "phone": user.phone,
            "password": password,
            "role": user.role,
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
