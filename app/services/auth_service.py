"""Auth business logic: xác thực, cấp/rotate/revoke refresh token.

Refresh token là opaque (stateful trong DB). Access token là JWT (stateless).
tenant_id LUÔN lấy từ token/user, không bao giờ từ request body.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    generate_refresh_token,
    hash_password,
    hash_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.services import tenant_service

_settings = get_settings()


@dataclass
class IssuedSession:
    """Kết quả cấp phiên: access token + raw refresh + csrf (router set cookie)."""

    user: User
    access_token: str
    refresh_token_raw: str
    csrf_token: str
    expires_in: int


def _build_access_token(user: User) -> str:
    return create_access_token(
        user_id=user.id,
        tenant_id=user.tenant_id,
        role=user.role,
        branch_id=user.branch_id,
    )


async def authenticate(
    db: AsyncSession, phone: str, password: str, slug: str | None = None
) -> User:
    """Tìm user active theo phone và verify password.

    phone unique theo (tenant_id, phone) — có thể trùng giữa các tenant.
    slug (mã cửa hàng) optional — tenant context chống nhập nhằng đa tenant:
    - CÓ slug → giới hạn ứng viên về đúng tenant (uq tenant_id+phone → tối đa 1).
    - KHÔNG slug (rỗng/space coi như không có) → tìm TOÀN CỤC (backward-compat
      giai đoạn 1; sẽ siết bắt buộc ở giai đoạn 2).
    Mọi lỗi (sai slug/phone/password) → cùng 401 INVALID_CREDENTIALS (chống dò tenant).
    """
    stmt = select(User).where(User.phone == phone, User.status == "active")
    if slug is not None and slug.strip():
        tenant = await tenant_service.get_tenant_by_slug(db, slug)
        if tenant is None:
            raise APIError(401, "INVALID_CREDENTIALS", "Sai số điện thoại hoặc mật khẩu")
        stmt = stmt.where(User.tenant_id == tenant.id)
    result = await db.execute(stmt)
    for user in result.scalars().all():
        if verify_password(password, user.password_hash):
            return user
    raise APIError(401, "INVALID_CREDENTIALS", "Sai số điện thoại hoặc mật khẩu")


async def issue_session(db: AsyncSession, user: User) -> IssuedSession:
    """Cấp access token + lưu refresh token mới (hash) vào DB."""
    refresh_raw = generate_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=_settings.jwt_refresh_ttl_days)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(refresh_raw),
            expires_at=expires_at,
        )
    )
    await db.commit()
    return IssuedSession(
        user=user,
        access_token=_build_access_token(user),
        refresh_token_raw=refresh_raw,
        csrf_token=generate_csrf_token(),
        expires_in=_settings.jwt_access_ttl_minutes * 60,
    )


async def _find_active_refresh(db: AsyncSession, refresh_raw: str) -> RefreshToken:
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_raw))
    )
    token = result.scalar_one_or_none()
    now = datetime.now(timezone.utc)
    if token is None or token.revoked_at is not None or token.expires_at <= now:
        raise APIError(401, "INVALID_REFRESH_TOKEN", "Refresh token không hợp lệ")
    return token


async def rotate_session(db: AsyncSession, refresh_raw: str) -> IssuedSession:
    """Rotate: revoke refresh cũ, cấp refresh mới + access token mới."""
    token = await _find_active_refresh(db, refresh_raw)

    user = await db.get(User, token.user_id)
    if user is None or user.status != "active":
        raise APIError(401, "INVALID_REFRESH_TOKEN", "Refresh token không hợp lệ")

    token.revoked_at = datetime.now(timezone.utc)
    new_raw = generate_refresh_token()
    expires_at = datetime.now(timezone.utc) + timedelta(days=_settings.jwt_refresh_ttl_days)
    db.add(
        RefreshToken(
            user_id=user.id,
            token_hash=hash_token(new_raw),
            expires_at=expires_at,
        )
    )
    await db.commit()
    return IssuedSession(
        user=user,
        access_token=_build_access_token(user),
        refresh_token_raw=new_raw,
        csrf_token=generate_csrf_token(),
        expires_in=_settings.jwt_access_ttl_minutes * 60,
    )


async def change_password(
    db: AsyncSession,
    user: User,
    current_password: str,
    new_password: str,
    current_refresh_raw: str | None = None,
) -> None:
    """Tự đổi MK: verify MK cũ → hash MK mới (bcrypt) → ĐĂNG XUẤT THIẾT BỊ KHÁC.

    - MK cũ sai → 400 INVALID_CURRENT_PASSWORD (KHÁC lỗi "MK mới yếu" = 422 ở schema).
    - Đổi hash qua hash_password (bcrypt) — KHÔNG tự hash kiểu khác.
    - Đăng xuất thiết bị khác: revoke MỌI refresh token còn hiệu lực của user, TRỪ
      token đang dùng (nhận diện bằng hash của refresh cookie hiện tại) → phiên hiện
      tại KHÔNG bị đá ra. Không có cookie → revoke hết (an toàn; user re-login).
      (access token JWT stateless còn hạn tới ~TTL trên thiết bị khác; chúng bị đăng
      xuất khi access hết hạn và refresh thất bại.)
    """
    if not verify_password(current_password, user.password_hash):
        raise APIError(400, "INVALID_CURRENT_PASSWORD", "Mật khẩu hiện tại không đúng")

    user.password_hash = hash_password(new_password)

    keep_hash = hash_token(current_refresh_raw) if current_refresh_raw else None
    stmt = (
        update(RefreshToken)
        .where(
            RefreshToken.user_id == user.id,
            RefreshToken.revoked_at.is_(None),
        )
        .values(revoked_at=datetime.now(timezone.utc))
    )
    if keep_hash is not None:
        stmt = stmt.where(RefreshToken.token_hash != keep_hash)
    await db.execute(stmt)
    await db.commit()


async def revoke_session(db: AsyncSession, refresh_raw: str | None) -> None:
    """Logout: revoke refresh token nếu còn hiệu lực (idempotent)."""
    if not refresh_raw:
        return
    result = await db.execute(
        select(RefreshToken).where(RefreshToken.token_hash == hash_token(refresh_raw))
    )
    token = result.scalar_one_or_none()
    if token is not None and token.revoked_at is None:
        token.revoked_at = datetime.now(timezone.utc)
        await db.commit()
