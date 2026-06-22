"""Dependencies dùng chung cho API: DB session, current user, phân quyền, pagination."""
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated

import jwt
from fastapi import Depends, Header, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import APIError
from app.core.security import decode_access_token
from app.core.tenant_ctx import set_current_tenant
from app.models.admin import Admin
from app.models.user import User

DbSession = Annotated[AsyncSession, Depends(get_db)]


async def get_current_user(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> User:
    """Verify JWT access token (Bearer), load user, check status active.

    tenant_id/branch_id/role lấy từ token; user nguồn sự thật trong DB.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(401, "NOT_AUTHENTICATED", "Thiếu access token")
    token = authorization[7:].strip()

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise APIError(401, "TOKEN_EXPIRED", "Access token đã hết hạn") from exc
    except jwt.PyJWTError as exc:
        raise APIError(401, "INVALID_TOKEN", "Access token không hợp lệ") from exc

    if payload.get("type") != "access":
        raise APIError(401, "INVALID_TOKEN", "Sai loại token")

    # RLS R2: set tenant context từ CLAIM (trước khi đọc DB) → after_begin đưa vào
    # GUC app.current_tenant_id cho MỌI query của request (kể cả load user dưới đây).
    # Lấy từ claim (không từ user đã load) để tránh chicken-and-egg khi users bật RLS.
    set_current_tenant(payload.get("tenant_id"))

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise APIError(401, "INVALID_TOKEN", "Access token không hợp lệ") from exc

    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise APIError(401, "USER_INACTIVE", "Tài khoản không hoạt động")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_role(*roles: str) -> Callable[[User], Awaitable[User]]:
    """Factory dependency: chỉ cho các role được liệt kê đi qua, ngược lại 403.

    Trả về current_user để endpoint dùng tiếp (tenant_id/branch_id/role).
    """

    async def _dep(current_user: CurrentUser) -> User:
        if current_user.role not in roles:
            raise APIError(403, "FORBIDDEN", "Bạn không có quyền thực hiện thao tác này")
        return current_user

    return _dep


# ── Admin (Super Admin) — NHÁNH MỚI, TÁCH HẲN get_current_user/require_role ──
async def get_current_admin(
    db: DbSession,
    authorization: Annotated[str | None, Header()] = None,
) -> Admin:
    """Verify admin JWT (Bearer), load admin từ bảng `admins`.

    TÁCH HẲN get_current_user (KHÔNG đụng tới nó):
    - assert type=='admin_access' → token user (type='access') bị 401 → cách ly 2 chiều.
    - KHÔNG gọi set_current_tenant: admin không thuộc tenant nào → GUC giữ rỗng (mặc
      định None → ''); nếu admin lỡ query bảng tenant thì RLS chặn (thấy 0 dòng).
    - load từ `admins` (KHÔNG db.get(User)) → admin id không nằm ở users vẫn OK.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise APIError(401, "NOT_AUTHENTICATED", "Thiếu access token")
    token = authorization[7:].strip()

    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError as exc:
        raise APIError(401, "TOKEN_EXPIRED", "Access token đã hết hạn") from exc
    except jwt.PyJWTError as exc:
        raise APIError(401, "INVALID_TOKEN", "Access token không hợp lệ") from exc

    if payload.get("type") != "admin_access":
        raise APIError(401, "INVALID_TOKEN", "Sai loại token")

    try:
        admin_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise APIError(401, "INVALID_TOKEN", "Access token không hợp lệ") from exc

    admin = await db.get(Admin, admin_id)
    if admin is None or admin.status != "active":
        raise APIError(401, "ADMIN_INACTIVE", "Tài khoản admin không hoạt động")
    return admin


CurrentAdmin = Annotated[Admin, Depends(get_current_admin)]


def require_admin(*roles: str) -> Callable[[Admin], Awaitable[Admin]]:
    """Guard admin (Super Admin). A1: mọi admin active đi qua.

    Truyền roles để siết theo cấp admin về sau (vd require_admin("super_admin")) —
    chỗ mở rộng; A1 chưa cần nên gọi require_admin() không tham số.
    """

    async def _dep(current_admin: CurrentAdmin) -> Admin:
        if roles and current_admin.role not in roles:
            raise APIError(403, "FORBIDDEN", "Bạn không có quyền thực hiện thao tác này")
        return current_admin

    return _dep


@dataclass
class Pagination:
    """Tham số phân trang đã được clamp (default limit=50, max=200)."""

    limit: int
    offset: int


def pagination(
    limit: Annotated[int, Query(description="Số bản ghi (max 200)")] = 50,
    offset: Annotated[int, Query(description="Bỏ qua bao nhiêu bản ghi")] = 0,
) -> Pagination:
    """Clamp limit về [1, 200] và offset về >= 0 (không 422 để không vỡ client cũ)."""
    safe_limit = 50 if limit <= 0 else min(limit, 200)
    safe_offset = max(0, offset)
    return Pagination(limit=safe_limit, offset=safe_offset)


PageParams = Annotated[Pagination, Depends(pagination)]
