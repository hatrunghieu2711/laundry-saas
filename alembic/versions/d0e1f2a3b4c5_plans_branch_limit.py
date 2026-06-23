"""plans/subscriptions — nền gói cước + giới hạn chi nhánh

- subscriptions.custom_max_branches (nullable): override giới hạn cho ca đặc biệt.
- UNIQUE(tenant_id) trên subscriptions: ép 1 subscription / tenant (bảng rỗng → an toàn).
- Seed 2 gói chuẩn: "Gói 1 chi nhánh" (max_branches=1), "Gói 3 chi nhánh" (max=3).
- ⭐ BACKFILL 3 tenant LIVE (BẮT BUỘC — không-subscription nay CHẶN tạo CN):
  2H (slug '2h') → Gói 3; '2h-dn'/'wic' → Gói 1.

⚠️ subscriptions STRICT RLS nhưng migration chạy bằng OWNER (bypass) → seed/backfill OK.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-06-23
"""
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d0e1f2a3b4c5"
down_revision: str | None = "c9d0e1f2a3b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_GOI_1 = "Gói 1 chi nhánh"
_GOI_3 = "Gói 3 chi nhánh"

_SEED_PLAN = """
INSERT INTO plans (id, name, price, max_branches, status)
SELECT gen_random_uuid(), :name, 0, :maxb, 'active'
WHERE NOT EXISTS (SELECT 1 FROM plans WHERE name = :name)
"""

# Backfill: gán subscription cho tenant theo slug, chỉ khi CHƯA có (idempotent).
_BACKFILL = """
DO $$
DECLARE p1 uuid; p3 uuid;
BEGIN
  SELECT id INTO p1 FROM plans WHERE name = 'Gói 1 chi nhánh' LIMIT 1;
  SELECT id INTO p3 FROM plans WHERE name = 'Gói 3 chi nhánh' LIMIT 1;
  INSERT INTO subscriptions (id, tenant_id, plan_id, status)
  SELECT gen_random_uuid(), t.id, p3, 'active' FROM tenants t
  WHERE t.slug = '2h'
    AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.tenant_id = t.id);
  INSERT INTO subscriptions (id, tenant_id, plan_id, status)
  SELECT gen_random_uuid(), t.id, p1, 'active' FROM tenants t
  WHERE t.slug IN ('2h-dn', 'wic')
    AND NOT EXISTS (SELECT 1 FROM subscriptions s WHERE s.tenant_id = t.id);
END $$;
"""


def upgrade() -> None:
    op.add_column(
        "subscriptions", sa.Column("custom_max_branches", sa.Integer(), nullable=True)
    )
    op.create_unique_constraint("uq_subscriptions_tenant", "subscriptions", ["tenant_id"])
    op.execute(sa.text(_SEED_PLAN).bindparams(name=_GOI_1, maxb=1))
    op.execute(sa.text(_SEED_PLAN).bindparams(name=_GOI_3, maxb=3))
    op.execute(_BACKFILL)


def downgrade() -> None:
    # Gỡ cột + ràng buộc. KHÔNG xóa seed/backfill data (vô hại; app đang chạy có thể cần).
    op.drop_constraint("uq_subscriptions_tenant", "subscriptions", type_="unique")
    op.drop_column("subscriptions", "custom_max_branches")
