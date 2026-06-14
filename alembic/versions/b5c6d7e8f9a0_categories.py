"""categories (danh mục dịch vụ) + services.category_id, backfill từ text category

Revision ID: b5c6d7e8f9a0
Revises: a4b5c6d7e8f9
Create Date: 2026-06-14 11:00:00.000000+00:00

Stage 4.3 — tách danh mục thành thực thể riêng:
  1. Tạo bảng categories.
  2. Thêm services.category_id (FK nullable).
  3. BACKFILL: với mỗi giá trị text `services.category` DISTINCT (gom trùng theo
     tenant), tạo 1 category rồi map services.category_id. KHÔNG mất dữ liệu.
  4. Bỏ cột text `services.category`.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


# revision identifiers, used by Alembic.
revision: str = 'b5c6d7e8f9a0'
down_revision: Union[str, None] = 'a4b5c6d7e8f9'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── 1. Bảng categories ─────────────────────────────────────────────
    op.create_table(
        "categories",
        sa.Column("id", UUID(as_uuid=True),
                  server_default=sa.text("gen_random_uuid()"), primary_key=True),
        sa.Column("tenant_id", UUID(as_uuid=True),
                  sa.ForeignKey("tenants.id"), nullable=False),
        sa.Column("name", sa.String(64), nullable=False),
        sa.Column("icon", sa.String(32), nullable=True),
        sa.Column("display_order", sa.Integer(), server_default="0", nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default="true", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True),
                  server_default=sa.text("now()"), nullable=False),
    )
    op.create_index(
        "ix_categories_tenant_active_order",
        "categories", ["tenant_id", "is_active", "display_order"],
    )

    # ── 2. services.category_id ────────────────────────────────────────
    op.add_column(
        "services",
        sa.Column("category_id", UUID(as_uuid=True),
                  sa.ForeignKey("categories.id"), nullable=True),
    )

    # ── 3. BACKFILL từ cột text `category` (gom trùng theo tenant) ─────
    # Tạo 1 category cho mỗi (tenant_id, category) khác NULL/rỗng. display_order
    # theo thứ tự xuất hiện (min display_order của dịch vụ trong nhóm, rồi name).
    op.execute(
        """
        INSERT INTO categories (id, tenant_id, name, display_order, is_active, created_at, updated_at)
        SELECT gen_random_uuid(), grp.tenant_id, grp.category,
               (row_number() OVER (
                    PARTITION BY grp.tenant_id
                    ORDER BY grp.min_order, grp.category
                ))::int - 1,
               true, now(), now()
        FROM (
            SELECT tenant_id, category, MIN(display_order) AS min_order
            FROM services
            WHERE category IS NOT NULL AND btrim(category) <> ''
            GROUP BY tenant_id, category
        ) AS grp;
        """
    )
    # Map services.category_id theo (tenant_id, name == category text).
    op.execute(
        """
        UPDATE services s
        SET category_id = c.id
        FROM categories c
        WHERE c.tenant_id = s.tenant_id
          AND c.name = s.category
          AND s.category IS NOT NULL AND btrim(s.category) <> '';
        """
    )

    # ── 4. Bỏ cột text cũ ──────────────────────────────────────────────
    op.drop_column("services", "category")


def downgrade() -> None:
    # Khôi phục cột text + đổ lại từ categories (best-effort).
    op.add_column("services", sa.Column("category", sa.String(64), nullable=True))
    op.execute(
        """
        UPDATE services s
        SET category = c.name
        FROM categories c
        WHERE c.id = s.category_id;
        """
    )
    op.drop_column("services", "category_id")
    op.drop_index("ix_categories_tenant_active_order", table_name="categories")
    op.drop_table("categories")
