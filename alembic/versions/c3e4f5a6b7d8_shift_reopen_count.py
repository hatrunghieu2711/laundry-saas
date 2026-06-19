"""shift reopen_count (Stage 6.37 — mở lại ca)

Đếm số lần ca bị MỞ LẠI (reopen) sau khi đã đóng — để chủ giám sát + FE cảnh báo.
Chi tiết ai/lúc nào/ca nào ghi ở audit_logs (action='shift.reopen'). Cột Integer NOT NULL
default 0, additive an toàn.

Revision ID: c3e4f5a6b7d8
Revises: b2d3e4f5a6c7
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c3e4f5a6b7d8"
down_revision: Union[str, None] = "b2d3e4f5a6c7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "shifts",
        sa.Column("reopen_count", sa.Integer(), nullable=False, server_default=sa.text("0")),
    )


def downgrade() -> None:
    op.drop_column("shifts", "reopen_count")
