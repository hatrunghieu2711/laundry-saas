"""branches.order_prefix — tiền tố order_code tùy biến per-branch

Revision ID: a1b2c3d4e5f6
Revises: b5c6d7e8f9a0
Create Date: 2026-06-15 09:00:00.000000+00:00

Stage 5.1 — owner đặt tiền tố mã đơn riêng mỗi chi nhánh:
  1. Thêm cột branches.order_prefix (String(16)).
  2. BACKFILL: order_prefix = code hiện tại (vd "B1") — đơn cũ giữ nguyên format.
  3. NOT NULL + unique (tenant_id, order_prefix) — 2 branch cùng tenant KHÔNG
     trùng prefix (tránh order_code đụng nhau qua unique (tenant_id, order_code)).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "b5c6d7e8f9a0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "branches", sa.Column("order_prefix", sa.String(16), nullable=True)
    )
    # Backfill = code (giữ format mã đơn cũ B1-/B2-...).
    op.execute("UPDATE branches SET order_prefix = code WHERE order_prefix IS NULL")
    op.alter_column("branches", "order_prefix", nullable=False)
    # Unique trong tenant — gồm cả branch đã soft-delete (order_code không tái dùng).
    op.create_index(
        "uq_branches_tenant_order_prefix",
        "branches",
        ["tenant_id", "order_prefix"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_branches_tenant_order_prefix", table_name="branches")
    op.drop_column("branches", "order_prefix")
