"""Security primitives: bcrypt password hashing, JWT, token/CSRF helpers."""
import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings

_settings = get_settings()
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


# ── Password ────────────────────────────────────────────────────────────
def hash_password(plain: str) -> str:
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_context.verify(plain, hashed)


# ── Access token (JWT) ──────────────────────────────────────────────────
def create_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    branch_id: uuid.UUID | None,
) -> str:
    """JWT access token (30 phút). Claims: sub, tenant_id, role, branch_id."""
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "branch_id": str(branch_id) if branch_id else None,
        "type": "access",
        "iat": now,
        "exp": now + timedelta(minutes=_settings.jwt_access_ttl_minutes),
    }
    return jwt.encode(payload, _settings.jwt_secret, algorithm=_settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """Giải mã + verify chữ ký & hạn. Raise jwt.PyJWTError nếu sai/hết hạn."""
    return jwt.decode(token, _settings.jwt_secret, algorithms=[_settings.jwt_algorithm])


# ── Refresh token (opaque, stateful trong DB) ───────────────────────────
def generate_refresh_token() -> str:
    """Sinh refresh token ngẫu nhiên (raw, chỉ nằm trong cookie httpOnly)."""
    return secrets.token_urlsafe(48)


def hash_token(raw: str) -> str:
    """SHA-256 — lưu hash vào DB, không bao giờ lưu raw refresh token."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ── CSRF (double submit) ────────────────────────────────────────────────
def generate_csrf_token() -> str:
    return secrets.token_urlsafe(32)
