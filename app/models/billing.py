"""Plan & Subscription — bảng baseline cho SaaS subscription.

CHƯA viết logic ở MVP — chỉ tạo bảng trong baseline (làm khi có khách ngoài đầu tiên).
"""
import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Money, TimestampMixin, UpdatedAtMixin, uuid_pk


class Plan(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "plans"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(100), nullable=False)
    price: Mapped[Decimal] = mapped_column(Money, nullable=False, server_default="0")
    max_branches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")


class Subscription(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "subscriptions"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("plans.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
    # Override giới hạn chi nhánh cho ca đặc biệt (>3). NULL → dùng plan.max_branches.
    custom_max_branches: Mapped[int | None] = mapped_column(Integer, nullable=True)
    current_period_start: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    current_period_end: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    __table_args__ = (Index("ix_subscriptions_tenant_id", "tenant_id"),)
