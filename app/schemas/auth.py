"""Pydantic v2 schemas cho auth."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class LoginRequest(BaseModel):
    phone: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=1, max_length=128)
    # Mã cửa hàng (slug tenant) — optional giai đoạn 1 (client cũ không gửi vẫn chạy).
    slug: str | None = Field(default=None, max_length=100)


class ChangePasswordRequest(BaseModel):
    """Tự đổi mật khẩu (user đang đăng nhập). new_password min 6 (như UserCreate)."""

    current_password: str = Field(min_length=1, max_length=128)
    new_password: str = Field(min_length=6, max_length=128)


class TokenResponse(BaseModel):
    """Trả về sau login/refresh. Refresh token nằm ở cookie, KHÔNG ở body."""

    access_token: str
    token_type: str = "bearer"
    expires_in: int  # giây
    csrf_token: str  # client gửi lại qua header X-CSRF-Token


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID | None
    role: str
    full_name: str
    phone: str
    email: str | None
    # Tên TIỆM (tenant.name) — FE hiển thị ở menu/topbar. Gán transient ở /auth/me
    # (join tenant theo tenant_id). None nếu không đọc được tenant.
    tenant_name: str | None = None
    # Slug tiệm (tenant.slug) — nguồn ĐÁNG TIN cho QR bill (track/{slug}/{order_code}).
    # Gán transient ở /auth/me (CÙNG query với tenant_name). None nếu không đọc được.
    tenant_slug: str | None = None
    # Hạn GÓI (Stage Subscription-expiry) — FE hiện banner + disable nút tạo đơn khi
    # 'expired'. Gán transient ở /auth/me (subscription_info). Mặc định 'active' (vô hạn).
    subscription_status: str = "active"  # active | warning | grace | expired
    subscription_expires_at: datetime | None = None
    subscription_days_left: int | None = None
    # Panel "Thông tin tiệm" (owner) — gói + CN dùng/max + liên hệ hỗ trợ. Gán transient
    # ở /auth/me (plan_name/branch_max từ subscription_info sẵn; branch_count 1 count query;
    # support_* từ config). Đều None mặc định → client cũ không gãy.
    plan_name: str | None = None
    branch_max: int | None = None      # = effective_max_branches (custom ?? plan)
    branch_count: int | None = None    # số CN ĐANG hoạt động
    support_contact: str | None = None
    support_zalo: str | None = None
