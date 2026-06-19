"""shift cash_diff_reason (Stage 6.33)

Lý do lệch tiền khi đóng ca — BẮT BUỘC (enforce ở service) khi cash_difference≠0.
Cột Text nullable, additive an toàn.

Revision ID: b2d3e4f5a6c7
Revises: a1c2e3f4d5b6
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "b2d3e4f5a6c7"
down_revision: Union[str, None] = "a1c2e3f4d5b6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("cash_diff_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("shifts", "cash_diff_reason")
