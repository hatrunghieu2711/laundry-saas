"""Payment — IMMUTABLE. Chỉ INSERT, không bao giờ UPDATE/DELETE.

QUY TẮC:
- Mọi payment PHẢI có shift_id trỏ tới một shift đang OPEN lúc tạo (NOT NULL).
- Quy ước dấu: + payment/resolve_debt/adjustment dương; − refund/cancel_paid;
  debt có amount = 0 trong dòng tiền.
- reason BẮT BUỘC (validate ở service) với refund/adjustment/cancel_paid.
"""
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Money, TimestampMixin, uuid_pk


class Payment(TimestampMixin, Base):
    __tablename__ = "payments"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False
    )
    order_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("orders.id"), nullable=True
    )
    # Mọi payment PHẢI thuộc một shift — NOT NULL, không ngoại lệ.
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)  # âm cho refund/cancel
    payment_method: Mapped[str] = mapped_column(String(16), nullable=False)  # cash|transfer|qr|cod
    transaction_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reference_payment_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("payments.id"), nullable=True
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    __table_args__ = (
        Index("ix_payments_tenant_branch_created", "tenant_id", "branch_id", "created_at"),
        Index("ix_payments_shift_id", "shift_id"),
        Index("ix_payments_order_id", "order_id"),
    )
