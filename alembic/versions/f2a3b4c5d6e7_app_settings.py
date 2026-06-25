"""app_settings — cấu hình hệ thống key-value (NGOÀI RLS)

Bảng global (không tenant_id) cho config hệ thống — hiện: mẫu in chuẩn system-wide
(key='default_receipt'). NGOÀI RLS như tenants/plans/admins: KHÔNG ENABLE ROW LEVEL
SECURITY (admin GUC rỗng phải đọc/ghi). laundry_app TỰ có CRUD qua ALTER DEFAULT
PRIVILEGES FOR ROLE laundry (R1); thêm GRANT tường minh (guarded) cho chắc.

Revision ID: f2a3b4c5d6e7
Revises: e1f2a3b4c5d6
Create Date: 2026-06-25
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f2a3b4c5d6e7"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(length=64), nullable=False),
        sa.Column("value", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )
    # ⚠️ CỐ Ý KHÔNG "ENABLE ROW LEVEL SECURITY": app_settings NGOÀI RLS (như tenants/plans/
    # admins). GRANT tường minh cho laundry_app (guarded — không fail nếu role chưa có).
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'laundry_app') THEN
            GRANT SELECT, INSERT, UPDATE, DELETE ON app_settings TO laundry_app;
          END IF;
        END $$;
        """
    )


def downgrade() -> None:
    op.drop_table("app_settings")
