"""tenant_settings.auto_print_copy2 — tự động in liên 2 (TÁCH RIÊNG auto_print_receipt)

Liên 2 (nhãn dán túi) tự động trước nay ĐI CHUNG auto_print_receipt (OrderNew in
[bill, lien2] khi auto_print bật). Tách ra cột riêng → bật/tắt độc lập in bill.

⚠️ BACKFILL = auto_print_receipt → giữ NGUYÊN hành vi hiện tại (tenant đang auto_print
bill thì liên 2 vẫn tự in; đang tắt thì cả hai tắt). server_default true khớp default
của auto_print_receipt.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-06-24
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "d0e1f2a3b4c5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "tenant_settings",
        sa.Column(
            "auto_print_copy2", sa.Boolean(), nullable=False, server_default=sa.text("true")
        ),
    )
    # ⚠️ BACKFILL: bằng auto_print_receipt hiện tại → không đổi hành vi tenant đang chạy.
    op.execute("UPDATE tenant_settings SET auto_print_copy2 = auto_print_receipt")


def downgrade() -> None:
    op.drop_column("tenant_settings", "auto_print_copy2")
