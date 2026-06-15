"""price_rules + discount_logs + order adjustment columns (phụ thu/giảm giá thật)

Revision ID: c7d8e9f0a1b2
Revises: a1b2c3d4e5f6
Create Date: 2026-06-15 11:30:00.000000+00:00

Stage 5.4 — phụ thu & giảm giá vào TIỀN THẬT:
  1. Bảng price_rules: quy tắc tự áp theo ngày (surcharge|discount, percent|fixed).
  2. orders: thêm subtotal/surcharge_amount/discount_amount + reason; BACKFILL
     subtotal = total_amount (đơn cũ: không phụ thu/giảm).
  3. Bảng discount_logs: nhật ký giảm giá (ai/đơn/số tiền/lý do) cho báo cáo.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f0a1b2"
down_revision: Union[str, None] = "a1b2c3d4e5f6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── price_rules ──────────────────────────────────────────────────────────
    op.create_table(
        "price_rules",
        sa.Column("id", UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("value_type", sa.String(length=16), nullable=False),
        sa.Column("value", sa.Numeric(14, 2), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("start_date", sa.Date(), nullable=False),
        sa.Column("end_date", sa.Date(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_price_rules_tenant_active", "price_rules",
                    ["tenant_id", "is_active"])
    op.create_index("ix_price_rules_tenant_type_dates", "price_rules",
                    ["tenant_id", "type", "start_date", "end_date"])

    # ── orders: cột phụ thu/giảm (snapshot) ──────────────────────────────────
    op.add_column("orders", sa.Column("subtotal", sa.Numeric(14, 0),
                  server_default="0", nullable=False))
    op.add_column("orders", sa.Column("surcharge_amount", sa.Numeric(14, 0),
                  server_default="0", nullable=False))
    op.add_column("orders", sa.Column("discount_amount", sa.Numeric(14, 0),
                  server_default="0", nullable=False))
    op.add_column("orders", sa.Column("surcharge_reason", sa.Text(), nullable=True))
    op.add_column("orders", sa.Column("discount_reason", sa.Text(), nullable=True))
    # BACKFILL: đơn cũ chưa có phụ thu/giảm → subtotal = total_amount.
    op.execute("UPDATE orders SET subtotal = total_amount")

    # ── discount_logs ────────────────────────────────────────────────────────
    op.create_table(
        "discount_logs",
        sa.Column("id", UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", UUID(as_uuid=True), nullable=False),
        sa.Column("branch_id", UUID(as_uuid=True), nullable=False),
        sa.Column("order_id", UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", UUID(as_uuid=True), nullable=True),
        sa.Column("amount", sa.Numeric(14, 0), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_discount_logs_tenant_created", "discount_logs",
                    ["tenant_id", "created_at"])
    op.create_index("ix_discount_logs_tenant_user", "discount_logs",
                    ["tenant_id", "user_id"])
    op.create_index("ix_discount_logs_order_id", "discount_logs", ["order_id"])


def downgrade() -> None:
    op.drop_index("ix_discount_logs_order_id", table_name="discount_logs")
    op.drop_index("ix_discount_logs_tenant_user", table_name="discount_logs")
    op.drop_index("ix_discount_logs_tenant_created", table_name="discount_logs")
    op.drop_table("discount_logs")

    op.drop_column("orders", "discount_reason")
    op.drop_column("orders", "surcharge_reason")
    op.drop_column("orders", "discount_amount")
    op.drop_column("orders", "surcharge_amount")
    op.drop_column("orders", "subtotal")

    op.drop_index("ix_price_rules_tenant_type_dates", table_name="price_rules")
    op.drop_index("ix_price_rules_tenant_active", table_name="price_rules")
    op.drop_table("price_rules")
