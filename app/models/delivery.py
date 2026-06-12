"""Delivery — giao hàng + COD.

COD: khi shipper xác nhận đã thu, tạo payment (method=cod) vào SHIFT CỦA SHIPPER.
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Money, TimestampMixin, uuid_pk


class Delivery(TimestampMixin, Base):
    __tablename__ = "deliveries"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=False
    )
    shipper_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    delivery_status: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="assigned"
    )
    cod_amount: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    assigned_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_deliveries_shipper_status", "shipper_id", "delivery_status"),
        Index("ix_deliveries_order_id", "order_id"),
    )
