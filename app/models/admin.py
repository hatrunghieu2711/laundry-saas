"""Admin — Super Admin đứng TRÊN tenant (KHÔNG tenant_id/branch_id).

NGOÀI RLS (như tenants/plans): admin không có tenant_id để policy chiếu. phone
UNIQUE TOÀN CỤC (không theo tenant). Tách HẲN bảng users — không FK, không role tenant.
"""
import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UpdatedAtMixin, uuid_pk


class Admin(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "admins"

    id: Mapped[uuid.UUID] = uuid_pk()
    phone: Mapped[str] = mapped_column(String(32), nullable=False, unique=True)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    full_name: Mapped[str] = mapped_column(String(255), nullable=False)
    role: Mapped[str] = mapped_column(String(32), nullable=False, server_default="super_admin")
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
