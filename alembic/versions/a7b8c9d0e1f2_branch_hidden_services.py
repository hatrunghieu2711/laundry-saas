"""branch_hidden_services — ẩn/hiện dịch vụ theo chi nhánh (+ RLS strict)

Bảng mới: mỗi dòng = 1 dịch vụ ẩn ở 1 branch. Rỗng = hành vi cũ (không backfill).
RLS: STRICT theo tenant_id (giống 14 bảng tenant_id trực tiếp) — cùng pattern NULLIF,
KHÔNG FORCE. GRANT laundry_app tự có qua ALTER DEFAULT PRIVILEGES FOR ROLE laundry (R1,
bảng do owner tạo). ⚠️ BẮT BUỘC enable RLS + policy, nếu không laundry_app thấy mọi tenant.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-06-21
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a7b8c9d0e1f2"
down_revision: str | None = "f6a7b8c9d0e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_T = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"


def upgrade() -> None:
    op.create_table(
        "branch_hidden_services",
        sa.Column("id", sa.UUID(), server_default=sa.text("gen_random_uuid()"), nullable=False),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("branch_id", sa.UUID(), nullable=False),
        sa.Column("service_id", sa.UUID(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"]),
        sa.ForeignKeyConstraint(["branch_id"], ["branches.id"]),
        sa.ForeignKeyConstraint(["service_id"], ["services.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("branch_id", "service_id", name="uq_branch_hidden_service"),
    )
    op.create_index(
        "ix_branch_hidden_tenant_branch", "branch_hidden_services", ["tenant_id", "branch_id"]
    )
    # RLS strict (KHÔNG FORCE — owner bypass để migrate/fix; app laundry_app bị áp).
    op.execute("ALTER TABLE branch_hidden_services ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON branch_hidden_services "
        f"USING (tenant_id = {_T}) "
        f"WITH CHECK (tenant_id = {_T})"
    )


def downgrade() -> None:
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON branch_hidden_services")
    op.drop_table("branch_hidden_services")
