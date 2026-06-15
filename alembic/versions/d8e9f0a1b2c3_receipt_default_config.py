"""tenant_settings.receipt_default_config — mẫu phiếu mặc định per-tenant

Revision ID: d8e9f0a1b2c3
Revises: c7d8e9f0a1b2
Create Date: 2026-06-16 09:00:00.000000+00:00

Stage 5.10 — owner "Lưu làm mẫu mặc định" + "Khôi phục mẫu mặc định". NULL =
chưa lưu → fallback mẫu gốc nền tảng (DEFAULT_RECEIPT trong code).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSONB

# revision identifiers, used by Alembic.
revision: str = "d8e9f0a1b2c3"
down_revision: Union[str, None] = "c7d8e9f0a1b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column("receipt_default_config", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tenant_settings", "receipt_default_config")
