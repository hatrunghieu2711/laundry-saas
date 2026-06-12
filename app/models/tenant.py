"""Tenant — đơn vị thuê bao (một chuỗi giặt ủi)."""
import uuid

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import TimestampMixin, UpdatedAtMixin, uuid_pk


class Tenant(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "tenants"

    id: Mapped[uuid.UUID] = uuid_pk()
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    slug: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(32), nullable=False, server_default="active")
