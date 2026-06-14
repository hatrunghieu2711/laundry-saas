"""Category — danh mục dịch vụ (thực thể riêng, Stage 4.3).

Trước đây `services.category` là text tự do; nay tách thành bảng `categories`
(có icon + thứ tự hiển thị) để owner quản lý tập trung, dịch vụ tham chiếu
`category_id`. Tenant-scoped. Soft delete qua is_active.
"""
import uuid

from sqlalchemy import Boolean, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UpdatedAtMixin, uuid_pk


class Category(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    # icon: tên icon hoặc emoji (vd "🧺", "👕"); null = dùng icon mặc định ở UI.
    icon: Mapped[str | None] = mapped_column(String(32), nullable=True)
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        Index(
            "ix_categories_tenant_active_order",
            "tenant_id", "is_active", "display_order",
        ),
    )
