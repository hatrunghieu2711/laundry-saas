"""shifts.handover_to_owner + cash_left_for_next — rút nộp chủ khi đóng ca

Revision ID: e9f0a1b2c3d4
Revises: d8e9f0a1b2c3
Create Date: 2026-06-16 11:30:00.000000+00:00

Stage 6.2 — đóng ca có thể RÚT tiền nộp chủ. handover_to_owner là tiền ra khỏi két
SAU đối soát (không vào expected). cash_left_for_next = closing_cash_actual −
handover_to_owner → gợi ý đầu ca sau. Cả 2 nullable (chỉ set khi đóng ca).
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e9f0a1b2c3d4"
down_revision: Union[str, None] = "d8e9f0a1b2c3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("handover_to_owner", sa.Numeric(14, 0), nullable=True))
    op.add_column("shifts", sa.Column("cash_left_for_next", sa.Numeric(14, 0), nullable=True))


def downgrade() -> None:
    op.drop_column("shifts", "cash_left_for_next")
    op.drop_column("shifts", "handover_to_owner")
