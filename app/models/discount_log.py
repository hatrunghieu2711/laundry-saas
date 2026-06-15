"""DiscountLog — nhật ký mỗi lần GIẢM GIÁ một đơn (Stage 5.4).

Ghi khi tạo đơn có discount_amount > 0: ai giảm / đơn nào / số tiền / lý do / giờ.
Nguồn cho báo cáo GET /reports/discounts (tổng giảm theo nhân viên, theo ngày).
Chỉ INSERT (append-only, không sửa).
"""
import uuid
from decimal import Decimal

from sqlalchemy import ForeignKey, Index, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Money, TimestampMixin, uuid_pk


class DiscountLog(TimestampMixin, Base):
    __tablename__ = "discount_logs"

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
    # Ai giảm (người tạo đơn). Nullable phòng user bị xóa cứng (không xảy ra ở MVP).
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_discount_logs_tenant_created", "tenant_id", "created_at"),
        Index("ix_discount_logs_tenant_user", "tenant_id", "user_id"),
        Index("ix_discount_logs_order_id", "order_id"),
    )
