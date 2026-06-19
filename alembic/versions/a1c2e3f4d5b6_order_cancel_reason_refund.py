"""order cancel_reason + refund_amount (Stage 6.28)

Hủy đơn có lý do (bắt buộc, enforce ở service) + số tiền đã hoàn lúc hủy.
refund_amount NUMERIC(14,0) NOT NULL default 0 (đồng VND, không số lẻ).

Revision ID: a1c2e3f4d5b6
Revises: f0a1b2c3d4e5
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1c2e3f4d5b6"
down_revision: Union[str, None] = "f0a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("orders", sa.Column("cancel_reason", sa.Text(), nullable=True))
    op.add_column(
        "orders",
        sa.Column(
            "refund_amount",
            sa.Numeric(14, 0),
            nullable=False,
            server_default=sa.text("0"),
        ),
    )


def downgrade() -> None:
    op.drop_column("orders", "refund_amount")
    op.drop_column("orders", "cancel_reason")
