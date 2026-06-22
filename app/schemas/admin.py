"""Pydantic v2 schemas cho admin (Super Admin). A1: auth; A2: tạo tenant."""
import re
import uuid

from pydantic import BaseModel, ConfigDict, Field, field_validator

_SLUG_RE = re.compile(r"^[a-z0-9-]+$")


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


# ── A2: tạo tenant (tiệm + CN đầu + owner + settings) ───────────────────────
class TenantCreate(BaseModel):
    """Admin tạo tenant mới. slug chuẩn hóa lowercase+trim, chỉ [a-z0-9-]."""

    name: str = Field(min_length=1, max_length=255)
    slug: str = Field(min_length=1, max_length=100)
    owner_full_name: str = Field(min_length=1, max_length=255)
    owner_phone: str = Field(min_length=1, max_length=32)
    # Thiếu → service sinh ngẫu nhiên (secrets) + trả trong response 1 lần.
    owner_password: str | None = Field(default=None, min_length=6, max_length=128)
    branch_name: str = Field(default="Chi nhánh 1", min_length=1, max_length=255)
    branch_address: str | None = Field(default=None, max_length=500)
    branch_phone: str | None = Field(default=None, max_length=32)

    @field_validator("slug")
    @classmethod
    def _normalize_slug(cls, v: str) -> str:
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("Slug chỉ gồm chữ thường, số và dấu gạch ngang")
        return v


class TenantCreateOut(BaseModel):
    """Đầu ra tạo tenant. temp_password plaintext — admin gửi chủ mới, HIỆN 1 LẦN."""

    tenant_id: uuid.UUID
    slug: str
    owner_phone: str
    temp_password: str
    branch_code: str
