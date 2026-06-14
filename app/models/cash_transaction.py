"""CashTransaction — sổ quỹ thu-chi ngoài đơn hàng (Stage 4.2). IMMUTABLE.

QUY TẮC (giống payments):
- Chỉ INSERT; không bao giờ UPDATE/DELETE. Sửa sai = ghi giao dịch đối ứng.
  Enforce ở DB bằng trigger cash_transactions_no_update_delete.
- Mọi giao dịch PHẢI thuộc một shift đang OPEN lúc tạo (shift_id NOT NULL) —
  thu/chi đều ảnh hưởng dòng tiền ca, giống payments.
- amount LUÔN DƯƠNG (magnitude). Dấu (vào/ra két) xác định bởi `type`:
  income = tiền vào, expense = tiền ra.
- payment_method mặc định 'cash' vì thu/chi tiền mặt ảnh hưởng KÉT; cho phép
  transfer/qr (không vào két nhưng vẫn ghi nhận dòng tiền).
"""
import uuid
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Index, String, Text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Money, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class CashTransaction(TimestampMixin, Base):
    __tablename__ = "cash_transactions"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False
    )
    # Mọi thu/chi PHẢI thuộc một shift — NOT NULL, không ngoại lệ.
    shift_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("shifts.id"), nullable=False
    )
    type: Mapped[str] = mapped_column(String(16), nullable=False)  # income | expense
    amount: Mapped[Decimal] = mapped_column(Money, nullable=False)  # luôn dương
    category: Mapped[str] = mapped_column(String(64), nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_method: Mapped[str] = mapped_column(
        String(16), nullable=False, server_default="cash"
    )  # cash | transfer | qr
    created_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    # Nhúng tên người ghi nhận (selectin, tránh N+1) — giống payments.
    created_by_user: Mapped["User"] = relationship(
        "User", foreign_keys=[created_by], lazy="selectin"
    )

    @property
    def created_by_name(self) -> str | None:
        return self.created_by_user.full_name if self.created_by_user else None

    __table_args__ = (
        Index(
            "ix_cash_transactions_tenant_branch_created",
            "tenant_id", "branch_id", "created_at",
        ),
        Index("ix_cash_transactions_shift_id", "shift_id"),
    )
