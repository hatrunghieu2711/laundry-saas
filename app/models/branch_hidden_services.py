"""BranchHiddenService — dịch vụ bị ẩn ở một chi nhánh (ẩn/hiện dịch vụ theo CN).

Mỗi dòng = MỘT dịch vụ ẩn ở MỘT branch. Bảng RỖNG = không ẩn gì = hành vi cũ (mọi
dịch vụ hiện ở mọi CN). Giá CHUNG — chỉ ẩn/hiện, không custom giá theo CN.
`tenant_id` DENORMALIZE để RLS strict (giống các bảng tenant_id trực tiếp).
"""
import uuid

from sqlalchemy import ForeignKey, Index, UniqueConstraint
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, uuid_pk


class BranchHiddenService(TimestampMixin, Base):
    __tablename__ = "branch_hidden_services"

    id: Mapped[uuid.UUID] = uuid_pk()
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), nullable=False
    )
    branch_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("branches.id"), nullable=False
    )
    service_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("services.id"), nullable=False
    )

    __table_args__ = (
        UniqueConstraint("branch_id", "service_id", name="uq_branch_hidden_service"),
        Index("ix_branch_hidden_tenant_branch", "tenant_id", "branch_id"),
    )
