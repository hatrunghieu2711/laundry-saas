"""Order & OrderItem.

QUY TẮC:
- order_status: created → washing → drying → ready → delivered → completed;
  cancelled từ mọi trạng thái trước delivered. Không nhảy lùi.
- order_code: prefix branch + sequence per branch (B1-00001), sinh bằng PG sequence.
- Unique (tenant_id, order_code). Không sửa total_amount sau khi có payment.
"""
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, Numeric, String, Text, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

if TYPE_CHECKING:
    from app.models.user import User

from app.core.database import Base
from app.models.base import Money, TimestampMixin, UpdatedAtMixin, uuid_pk


class Order(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False
    )
    customer_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("customers.id"), nullable=True
    )
    order_code: Mapped[str] = mapped_column(String(32), nullable=False)
    total_amount: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default="0")
    payment_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="unpaid"
    )
    order_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="created"
    )
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Tải kèm items (selectin) — quản lý qua collection (cascade insert/delete).
    items: Mapped[list["OrderItem"]] = relationship(
        lazy="selectin",
        cascade="all, delete-orphan",
        order_by="OrderItem.created_at",
    )
    # Nhúng tên người tạo đơn (selectin, tránh N+1).
    created_by_user: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by], lazy="selectin"
    )

    @property
    def created_by_name(self) -> str | None:
        return self.created_by_user.full_name if self.created_by_user else None

    __table_args__ = (
        UniqueConstraint("tenant_id", "order_code", name="uq_orders_tenant_order_code"),
        Index("ix_orders_tenant_branch_created", "tenant_id", "branch_id", "created_at"),
        Index("ix_orders_tenant_order_status", "tenant_id", "order_status"),
        Index("ix_orders_customer_id", "customer_id"),
    )


class OrderItem(TimestampMixin, Base):
    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    service_name: Mapped[str] = mapped_column(String(255), nullable=False)
    quantity: Mapped[Decimal] = mapped_column(Numeric(8, 2), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Money, nullable=False)
    subtotal: Mapped[Decimal] = mapped_column(Money, nullable=False)

    __table_args__ = (Index("ix_order_items_order_id", "order_id"),)
