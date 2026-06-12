"""payments immutability trigger and check constraints

Revision ID: 4f8dd4619d6c
Revises: 7b49f0b8703f
Create Date: 2026-06-12 17:18:22.429222+00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '4f8dd4619d6c'
down_revision: Union[str, None] = '7b49f0b8703f'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. payments IMMUTABLE: chặn UPDATE/DELETE ở DB level ────────────
    # Bảng payments chỉ được INSERT. Sửa sai = INSERT giao dịch đối ứng.
    op.execute(
        """
        CREATE OR REPLACE FUNCTION payments_no_update_delete()
        RETURNS TRIGGER AS $$
        BEGIN
            RAISE EXCEPTION
                'payments is immutable: % is not allowed (insert a reversing transaction instead)',
                TG_OP
                USING ERRCODE = 'restrict_violation';
        END;
        $$ LANGUAGE plpgsql;
        """
    )
    op.execute(
        """
        CREATE TRIGGER payments_no_update_delete
        BEFORE UPDATE OR DELETE ON payments
        FOR EACH ROW EXECUTE FUNCTION payments_no_update_delete();
        """
    )

    # ── 2. CHECK constraints cho các cột enum (giá trị theo CLAUDE.md) ──
    op.create_check_constraint(
        "ck_payments_transaction_type",
        "payments",
        "transaction_type IN "
        "('payment', 'refund', 'adjustment', 'debt', 'resolve_debt', 'cancel_paid')",
    )
    op.create_check_constraint(
        "ck_payments_payment_method",
        "payments",
        "payment_method IN ('cash', 'transfer', 'qr', 'cod')",
    )
    op.create_check_constraint(
        "ck_shifts_status",
        "shifts",
        "status IN ('open', 'closed')",
    )
    op.create_check_constraint(
        "ck_orders_order_status",
        "orders",
        "order_status IN "
        "('created', 'washing', 'drying', 'ready', 'delivered', 'completed', 'cancelled')",
    )
    op.create_check_constraint(
        "ck_orders_payment_status",
        "orders",
        "payment_status IN ('unpaid', 'partial', 'paid', 'refunded', 'debt')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_orders_payment_status", "orders", type_="check")
    op.drop_constraint("ck_orders_order_status", "orders", type_="check")
    op.drop_constraint("ck_shifts_status", "shifts", type_="check")
    op.drop_constraint("ck_payments_payment_method", "payments", type_="check")
    op.drop_constraint("ck_payments_transaction_type", "payments", type_="check")

    op.execute("DROP TRIGGER IF EXISTS payments_no_update_delete ON payments;")
    op.execute("DROP FUNCTION IF EXISTS payments_no_update_delete();")
