"""shift opening_diff + opening_diff_reason (Stage 6.55 — đối chiếu tiền đầu ca)

Vá lỗ hổng: mở ca nhập tiền đầu ca KHÁC tiền để lại ca trước (cash_left_for_next)
mà không cảnh báo/chặn → thất thoát không dấu vết. Nay open_shift đối chiếu; lệch →
bắt opening_diff_reason (nhất quán cash_diff_reason lúc đóng) + lưu opening_diff (có
dấu: âm=thiếu, dương=thừa). Cả 2 cột nullable (NULL khi khớp / ca đầu) — additive an toàn.

Revision ID: d4f5a6b7c8e9
Revises: c3e4f5a6b7d8
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d4f5a6b7c8e9"
down_revision: Union[str, None] = "c3e4f5a6b7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("shifts", sa.Column("opening_diff", sa.Numeric(14, 0), nullable=True))
    op.add_column("shifts", sa.Column("opening_diff_reason", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("shifts", "opening_diff_reason")
    op.drop_column("shifts", "opening_diff")
