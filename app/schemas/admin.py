"""Pydantic v2 schemas cho admin (Super Admin). Stage A1: access-token only."""
import uuid

from pydantic import BaseModel, ConfigDict, Field


class AdminLoginRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)


class AdminTokenResponse(BaseModel):
    """Trả về sau /admin/auth/login. A1: KHÔNG refresh/cookie (Stage sau nếu cần)."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # giây


class AdminOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    phone: str
    full_name: str
    role: str
