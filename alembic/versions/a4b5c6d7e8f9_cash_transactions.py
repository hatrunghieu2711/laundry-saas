"""cash_transactions (sổ quỹ thu-chi) + shifts total_income/total_expense

Revision ID: a4b5c6d7e8f9
Revises: f3a4b5c6d7e8
Create Date: 2026-06-14 09:00:00.000000+00:00

Stage 4.2 — sổ quỹ thu-chi ngoài đơn hàng. IMMUTABLE như payments (trigger chặn
UPDATE/DELETE). Đóng ca tính thêm thu-chi tiền mặt vào closing_cash_expected;
total_income/total_expense lưu phần tiền mặt (ảnh hưởng két).
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'a4b5c6d7e8f9'
down_revision: Union[str, None] = 'f3a4b5c6d7e8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Bảng cash_transactions ──────────────────────────────────────
    op.create_table(
        "cash_transactions",
        sa.Column(
            "id", UUID(as_uuid=True),
            server_default=sa.text("gen_random_uuid()"), primary_key=True,
        ),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("branch_id", UUID(as_uuid=True),
                  sa.ForeignKey("branches.id"), nullable=False),
        sa.Column("shift_id", UUID(as_uuid=True),
                  sa.ForeignKey("shifts.id"), nullable=False),
        sa.Column("type", sa.String(16), nullable=False),
        sa.Column("amount", sa.Numeric(14, 0), nullable=False),
        sa.Column("category", sa.String(64), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("payment_method", sa.String(16),
                  server_default="cash", nullable=False),
        sa.Column("created_by", UUID(as_uuid=True),
                  sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_cash_transactions_tenant_branch_created",
        "cash_transactions", ["tenant_id", "branch_id", "created_at"],
    )
    op.create_index(
        "ix_cash_transactions_shift_id", "cash_transactions", ["shift_id"],
    )

    # ── 2. CHECK constraints (enum + amount dương) ─────────────────────
    op.create_check_constraint(
        "ck_cash_transactions_type", "cash_transactions",
        "type IN ('income', 'expense')",
    )
    op.create_check_constraint(
        "ck_cash_transactions_payment_method", "cash_transactions",
        "payment_method IN ('cash', 'transfer', 'qr')",
    )
    op.create_check_constraint(
        "ck_cash_transactions_amount_positive", "cash_transactions",
        "amount > 0",
    )

    # ── 3. IMMUTABLE: chặn UPDATE/DELETE ở DB level (giống payments) ────
    op.execute(
        """
        CREATE OR REPLACE FUNCTION cash_transactions_no_update_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'cash_transactions is immutable: % is not allowed (insert a reversing transaction instead)',
                TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER cash_transactions_no_update_delete
        BEFORE UPDATE OR DELETE ON cash_transactions
        FOR EACH ROW EXECUTE FUNCTION cash_transactions_no_update_delete();
        """
    )

    # ── 4. Aggregate thu-chi tiền mặt trên shifts (tính lúc đóng ca) ───
    op.add_column("shifts", sa.Column("total_income", sa.Numeric(14, 0), nullable=True))
    op.add_column("shifts", sa.Column("total_expense", sa.Numeric(14, 0), nullable=True))


def downgrade() -> None:
    op.drop_column("shifts", "total_expense")
    op.drop_column("shifts", "total_income")

    op.execute(
        "DROP TRIGGER IF EXISTS cash_transactions_no_update_delete ON cash_transactions;"
    )
    op.execute("DROP FUNCTION IF EXISTS cash_transactions_no_update_delete();")
    op.drop_table("cash_transactions")
