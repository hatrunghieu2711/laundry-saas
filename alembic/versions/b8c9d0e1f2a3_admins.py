"""admins — bảng Super Admin (NGOÀI RLS)

Admin đứng TRÊN tenant: KHÔNG tenant_id/branch_id → KHÔNG ENABLE ROW LEVEL SECURITY
(giống tenants/plans; admin không có tenant_id để policy NULLIF(...) chiếu). phone
UNIQUE TOÀN CỤC (không theo tenant). Bảng do owner `laundry` tạo → laundry_app TỰ có
CRUD qua ALTER DEFAULT PRIVILEGES FOR ROLE laundry (R1) — KHÔNG cần GRANT tay.

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-06-22
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b8c9d0e1f2a3"
down_revision: str | None = "a7b8c9d0e1f2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admins",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("phone", sa.String(length=32), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=False),
        sa.Column("role", sa.String(length=32), server_default="super_admin", nullable=False),
        sa.Column("status", sa.String(length=32), server_default="active", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone", name="uq_admins_phone"),
    )
    # ⚠️ CỐ Ý KHÔNG "ENABLE ROW LEVEL SECURITY": admins NGOÀI RLS (như tenants/plans).
    # Admin không có tenant_id → policy tenant_isolation không chiếu được; nếu bật RLS
    # tenant-based admin sẽ tự chặn chính mình (GUC rỗng → thấy 0 dòng → không login).


def downgrade() -> None:
    op.drop_table("admins")
