"""Auth business logic: xác thực, cấp/rotate/revoke refresh token.

Refresh token là opaque (stateful trong DB). Access token là JWT (stateless).
tenant_id LUÔN lấy từ token/user, không bao giờ từ request body.
"""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.errors import APIError
from app.core.security import (
    create_access_token,
    generate_csrf_token,
    generate_refresh_token,
    hash_token,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User

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


async def authenticate(db: AsyncSession, phone: str, password: str) -> User:
    """Tìm user active theo phone và verify password.

    phone unique theo (tenant_id, phone) — về lý thuyết có thể trùng giữa các
    tenant; duyệt qua các ứng viên active và khớp password.
    """
    result = await db.execute(
        select(User).where(User.phone == phone, User.status == "active")
    )
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
