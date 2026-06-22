"""Auth ADMIN (Super Admin) — TÁCH HẲN auth user.

Admin đứng TRÊN tenant: KHÔNG tenant_id/branch_id. Stage A1 access-token ONLY
(không refresh/cookie/csrf — refresh_tokens FK→users.id không nhồi admin được).
Token type='admin_access' → guard cách ly 2 chiều với token user (type='access').
"""
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import create_admin_access_token, verify_password
from app.models.admin import Admin

_settings = get_settings()


@dataclass
class IssuedAdminSession:
    """Kết quả cấp phiên admin: access token (A1 không refresh)."""

    admin: Admin
    access_token: str
    expires_in: int


async def authenticate_admin(db: AsyncSession, phone: str, password: str) -> Admin:
    """Tìm admin active theo phone (UNIQUE toàn cục) + verify password.

    Mọi lỗi (sai phone / sai password / không active) → cùng 401 INVALID_CREDENTIALS
    (không lộ phone tồn tại). admins NGOÀI RLS → query chạy được dù GUC rỗng.
    """
    result = await db.execute(
        select(Admin).where(Admin.phone == phone, Admin.status == "active")
    )
    admin = result.scalar_one_or_none()
    if admin is None or not verify_password(password, admin.password_hash):
        raise APIError(401, "INVALID_CREDENTIALS", "Sai số điện thoại hoặc mật khẩu")
    return admin


def issue_admin_session(admin: Admin) -> IssuedAdminSession:
    """Cấp access token cho admin (A1: KHÔNG refresh/cookie)."""
    return IssuedAdminSession(
        admin=admin,
        access_token=create_admin_access_token(admin_id=admin.id, role=admin.role),
        expires_in=_settings.jwt_access_ttl_minutes * 60,
    )
