"""PriceRule — quy tắc phụ thu / giảm giá tự áp theo ngày (Stage 5.4).

Owner định nghĩa rule (vd "Phụ thu Tết" 20% từ 08/02–15/02). Khi tạo đơn nếu ngày
tạo (giờ VN) nằm trong [start_date, end_date] và đơn KHÔNG nhập tay phụ thu/giảm
thì rule được tự áp (snapshot vào order). Tenant-scoped, soft delete qua is_active.
"""
import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Boolean, Date, ForeignKey, Index, Numeric, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UpdatedAtMixin, uuid_pk


class PriceRule(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "price_rules"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    # surcharge (phụ thu, +) | discount (giảm, −)
    type: Mapped[str] = mapped_column(String(16), nullable=False)
    # percent (% trên tổng món) | fixed (số tiền cố định)
    value_type: Mapped[str] = mapped_column(String(16), nullable=False)
    # percent: 0..100 (cho phép lẻ vd 12.5); fixed: VND.
    value: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    start_date: Mapped[date] = mapped_column(Date, nullable=False)
    end_date: Mapped[date] = mapped_column(Date, nullable=False)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")

    __table_args__ = (
        Index("ix_price_rules_tenant_active", "tenant_id", "is_active"),
        Index("ix_price_rules_tenant_type_dates", "tenant_id", "type", "start_date", "end_date"),
    )
