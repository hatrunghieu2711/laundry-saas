"""tenant_settings.auto_print_receipt — bật/tắt tự in phiếu sau khi tạo đơn

Revision ID: f0a1b2c3d4e5
Revises: e9f0a1b2c3d4
Create Date: 2026-06-17 09:00:00.000000+00:00

Stage 6.8.2 — cấu hình auto-print per-tenant. MẶC ĐỊNH true để giữ đúng hành vi
2H hiện tại (tạo đơn → tự in). Tenant tắt → không auto-print.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "f0a1b2c3d4e5"
down_revision: Union[str, None] = "e9f0a1b2c3d4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column(
            "auto_print_receipt",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "auto_print_receipt")
