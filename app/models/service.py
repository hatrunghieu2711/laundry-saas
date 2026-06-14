"""Bảng giá dịch vụ động (thay hardcode) — Service + ServiceTier.

- per_unit: tính = quantity × unit_price (vd Áo Vest 60k/cái).
- tier: bậc cân cố định qua service_tiers (vd ≤3kg=60k trọn gói, không nhân).
  Bậc cuối có max_value=NULL + per_unit=true biểu diễn "vượt ngưỡng" tính
  theo đơn vị (vd >7kg=18k/kg).
- Tenant-scoped. Soft delete qua is_active. Giá đơn đã tạo KHÔNG đổi khi sửa
  bảng giá (order_items snapshot service_name + unit_price + subtotal).
"""
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import Boolean, ForeignKey, Index, Integer, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Money, TimestampMixin, UpdatedAtMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.category import Category

# unit/pricing_type lưu dạng String + validate ở Pydantic (đồng bộ với order_status).
UNITS = ("kg", "cai", "con", "bo", "luot")
PRICING_TYPES = ("per_unit", "tier")


class Service(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "services"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    unit: Mapped[str] = mapped_column(String(16), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default="0")
    pricing_type: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="per_unit"
    )
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")
    # Danh mục (thực thể riêng, Stage 4.3): gom tab màn tạo đơn; null = chưa phân loại.
    category_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("categories.id"), nullable=True
    )
    # "Hay chọn": owner đánh dấu dịch vụ thường dùng -> tab đầu màn tạo đơn.
    is_favorite: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")

    # Nhúng info danh mục (name/icon) vào ServiceOut — selectin tránh N+1.
    category: Mapped["Category | None"] = relationship("Category", lazy="selectin")

    tiers: Mapped[list["ServiceTier"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="ServiceTier.display_order",
    )

    __table_args__ = (
        Index(
            "ix_services_tenant_active_order",
            "tenant_id", "is_active", "display_order",
        ),
    )


class ServiceTier(TimestampMixin, Base):
    __tablename__ = "service_tiers"

    id: Mapped[uuid.UUID] = uuid_pk()
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=False
    )
    label: Mapped[str] = mapped_column(String(64), nullable=False)
    # max_value = ngưỡng trên (bao gồm) của bậc; NULL = bậc vượt ngưỡng (overflow).
    max_value: Mapped[Decimal | None] = mapped_column(Numeric(8, 2), nullable=True)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # per_unit=true: tính price × quantity (vd >7kg=18k/kg); false: giá trọn gói.
    per_unit: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="false")
    display_order: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")

    __table_args__ = (Index("ix_service_tiers_service_id", "service_id"),)
