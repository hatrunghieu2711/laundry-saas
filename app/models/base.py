"""Mixins & helpers dùng chung cho mọi ORM model.

Quy ước (theo CLAUDE.md):
- Mọi ID là UUID (server default gen_random_uuid() — PostgreSQL 16 core).
- Mọi timestamp là UTC (timestamptz), server default now().
- Mọi bảng có created_at; bảng mutable có thêm updated_at.
- Tiền dùng NUMERIC(14,0) (VND không số lẻ).
"""
from datetime import datetime

from sqlalchemy import DateTime, Numeric, func, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

# Kiểu cột tiền chuẩn của hệ thống: NUMERIC(14,0).
Money = Numeric(14, 0)


def uuid_pk() -> Mapped:
    """Cột PK UUID, sinh ở DB bằng gen_random_uuid()."""
    return mapped_column(
        UUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


class TimestampMixin:
    """created_at cho mọi bảng."""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class UpdatedAtMixin:
    """updated_at cho bảng mutable (tự cập nhật khi UPDATE)."""

    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
