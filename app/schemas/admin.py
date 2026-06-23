"""Pydantic v2 schemas cho admin (Super Admin). A1: auth; A2: tạo tenant; A3: quản tenant."""
import re
import uuid
from datetime import datetime
from typing import Literal

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


# ── A3: list / detail / sửa / khóa / reset MK owner ─────────────────────────
class TenantListItem(BaseModel):
    """1 dòng danh sách tenant + số liệu nhẹ (đếm trực tiếp qua set_config loop)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    n_branches: int
    n_users: int
    last_order_at: datetime | None
    # Plans-3: gói hiện tại (None khi chưa có subscription). Tên khớp SubscriptionOut.
    plan_id: uuid.UUID | None = None
    plan_name: str | None = None
    custom_max_branches: int | None = None
    effective_max_branches: int | None = None


class TenantAdminUpdate(BaseModel):
    """Admin sửa tenant. status đổi → service revoke refresh nếu khóa (chống khóa giả)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    slug: str | None = Field(default=None, min_length=1, max_length=100)
    status: Literal["active", "suspended"] | None = None

    @field_validator("slug")
    @classmethod
    def _normalize_slug(cls, v: str | None) -> str | None:
        if v is None:
            return v
        v = v.strip().lower()
        if not _SLUG_RE.match(v):
            raise ValueError("Slug chỉ gồm chữ thường, số và dấu gạch ngang")
        return v


class TenantAdminUpdateOut(BaseModel):
    """Kết quả sửa tenant. slug_changed=True → FE cảnh báo user phải nhập mã mới."""

    id: uuid.UUID
    name: str
    slug: str
    status: str
    slug_changed: bool


class TenantStatusOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    slug: str
    status: str


class ResetOwnerPasswordIn(BaseModel):
    # Chỉ định owner khi tenant có >1 owner; bỏ trống nếu đúng 1 owner.
    user_id: uuid.UUID | None = None


class ResetOwnerPasswordOut(BaseModel):
    """temp_password plaintext — admin gửi owner, HIỆN 1 LẦN."""

    owner_phone: str
    temp_password: str


# ── Plans-1: gói cước + giới hạn chi nhánh ──────────────────────────────────
class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    price: int
    max_branches: int | None
    status: str


class SetSubscriptionIn(BaseModel):
    plan_id: uuid.UUID
    # Override giới hạn cho ca đặc biệt (>3). Bỏ trống → dùng plan.max_branches.
    custom_max_branches: int | None = Field(default=None, ge=1)


class SubscriptionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: uuid.UUID
    plan_id: uuid.UUID
    plan_name: str
    plan_max_branches: int | None
    custom_max_branches: int | None
    effective_max_branches: int
