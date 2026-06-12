"""Dependencies dùng chung cho API: DB session, current user."""
import uuid
from typing import Annotated

import jwt
from fastapi import Depends, Header
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.errors import APIError
from app.core.security import decode_access_token
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

    try:
        user_id = uuid.UUID(payload["sub"])
    except (KeyError, ValueError) as exc:
        raise APIError(401, "INVALID_TOKEN", "Access token không hợp lệ") from exc

    user = await db.get(User, user_id)
    if user is None or user.status != "active":
        raise APIError(401, "USER_INACTIVE", "Tài khoản không hoạt động")
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]
