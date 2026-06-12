"""Branch — chi nhánh thuộc một tenant.

Soft delete qua status — KHÔNG xóa cứng (có lịch sử payment).
"""
import uuid

from sqlalchemy import ForeignKey, Index, String
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UpdatedAtMixin, uuid_pk


class Branch(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "branches"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(500), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # code: vd "B1", dùng làm prefix order_code.
    code: Mapped[str] = mapped_column(String(16), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")

    __table_args__ = (Index("ix_branches_tenant_id", "tenant_id"),)
