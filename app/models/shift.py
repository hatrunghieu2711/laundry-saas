"""Shift — ca làm việc tại một branch.

QUY TẮC:
- Mỗi branch TỐI ĐA MỘT shift open — enforce bằng partial unique index ở DB.
- Shift closed là bất biến.
- Đóng ca = reconciliation: tính closing_cash_expected, lưu cash_difference
  và các cột aggregate (tính MỘT LẦN lúc đóng ca).
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base
from app.models.base import Money, TimestampMixin, uuid_pk

if TYPE_CHECKING:
    from app.models.user import User


class Shift(TimestampMixin, Base):
    __tablename__ = "shifts"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False
    )
    opened_by: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    closed_by: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    opening_cash: Mapped[Decimal] = mapped_column(Money, nullable=False)
    # Reconciliation — tính lúc đóng ca.
    closing_cash_expected: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    closing_cash_actual: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    cash_difference: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    # Lý do lệch tiền (Stage 6.33) — BẮT BUỘC (enforce ở service) khi cash_difference≠0.
    cash_diff_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Aggregate — tính MỘT LẦN lúc đóng ca (ca đóng là immutable).
    total_cash: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    total_transfer: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    total_qr: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    total_cod: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    # Sổ quỹ thu-chi TIỀN MẶT ngoài đơn (Stage 4.2) — phần ảnh hưởng KÉT, tính
    # lúc đóng ca. (income/expense qua transfer/qr không vào két nên không gộp.)
    total_income: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    total_expense: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    orders_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Rút tiền nộp chủ khi đóng ca (Stage 6.2). handover_to_owner: tiền RA khỏi két
    # SAU đối soát (KHÔNG vào expected, KHÔNG phải chi phí). cash_left_for_next =
    # closing_cash_actual − handover_to_owner → gợi ý đầu ca sau.
    handover_to_owner: Mapped[Decimal | None] = mapped_column(Money, nullable=True)
    cash_left_for_next: Mapped[Decimal | None] = mapped_column(Money, nullable=True)

    # Số lần MỞ LẠI ca sau khi đóng (Stage 6.37) — chủ giám sát; chi tiết ở audit_logs.
    reopen_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    status: Mapped[str] = mapped_column(String(16), nullable=False, server_default="open")
    opened_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Nhúng tên người mở/đóng vào response (selectin, tránh N+1). Tên là thông
    # tin nội bộ tenant — an toàn cho mọi role xem; staff không cần GET /users.
    opened_by_user: Mapped["User"] = relationship(
        "User", foreign_keys=[opened_by], lazy="selectin"
    )
    closed_by_user: Mapped["User | None"] = relationship(
        "User", foreign_keys=[closed_by], lazy="selectin"
    )

    @property
    def opened_by_name(self) -> str | None:
        return self.opened_by_user.full_name if self.opened_by_user else None

    @property
    def closed_by_name(self) -> str | None:
        return self.closed_by_user.full_name if self.closed_by_user else None

    __table_args__ = (
        # Mỗi branch tối đa MỘT shift open — DB-level enforcement.
        Index(
            "one_open_shift_per_branch",
            "branch_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_shifts_tenant_branch_opened", "tenant_id", "branch_id", "opened_at"),
        Index("ix_shifts_branch_status", "branch_id", "status"),
    )
