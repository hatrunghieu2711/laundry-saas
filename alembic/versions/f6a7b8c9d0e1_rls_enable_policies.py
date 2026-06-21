"""RLS R3: bật Row-Level Security + policy cách ly tenant

Nền: R1 (role `laundry_app` non-bypass) + R2 (GUC `app.current_tenant_id` set mỗi txn).

Quyết định thiết kế:
- KHÔNG dùng FORCE: owner (`laundry`, chạy migration + data-fix) BỎ QUA RLS → migration
  sau không bị policy chặn (GUC rỗng lúc migrate sẽ lọc còn 0 dòng nếu FORCE → nguy hiểm).
  App (`laundry_app`, non-owner) BỊ áp policy → cách ly thật. Test cách ly dùng engine
  laundry_app (non-owner) nên KHÔNG cần FORCE.
- Cast AN TOÀN: NULLIF(current_setting('app.current_tenant_id', true), '')::uuid.
  ('' KHÔNG cast uuid được → lỗi; NULLIF → NULL → không match → thấy rỗng, không lỗi.
  missing_ok=true → GUC chưa set → NULL.)
- USING (lọc đọc) + WITH CHECK (chặn ghi sang tenant khác) — cần CẢ HAI.
- `users`: policy "permissive-when-empty" — GUC rỗng (login/refresh) → đọc TOÀN CỤC
  (authenticate tìm phone đa tenant + rotate_session load user); GUC set (authed) →
  chỉ tenant mình = lưới defense-in-depth. (Không để users hoàn toàn ngoài RLS.)
- Bảng con KHÔNG có tenant_id trực tiếp (order_items / service_tiers /
  order_tracking_logs): policy GIÁN TIẾP qua parent (EXISTS) — không đổi schema/code;
  app vốn lọc qua join nên đây là lưới phụ. Denormalize tenant_id là tối ưu sau nếu cần.
- NGOÀI RLS: refresh_tokens (token opaque, refresh chạy GUC rỗng, không có tenant_id),
  tenants + plans (tra cứu/global; tenants có _ensure_own_tenant ở app), alembic_version.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-06-21
"""
from collections.abc import Sequence

from alembic import op

revision: str = "f6a7b8c9d0e1"
down_revision: str | None = "e5f6a7b8c9d0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Tenant hiện tại — an toàn với GUC rỗng/unset.
_T = "NULLIF(current_setting('app.current_tenant_id', true), '')::uuid"

# Bảng có tenant_id TRỰC TIẾP → policy chặt (đọc + ghi chỉ tenant mình).
_STRICT = [
    "orders", "payments", "shifts", "cash_transactions", "customers",
    "branches", "categories", "services", "price_rules", "discount_logs",
    "deliveries", "audit_logs", "tenant_settings", "subscriptions",
]

# Bảng con: (table, parent, fk_col) → policy gián tiếp qua parent.
_CHILD = [
    ("order_items", "orders", "order_id"),
    ("service_tiers", "services", "service_id"),
    ("order_tracking_logs", "orders", "order_id"),
]


def upgrade() -> None:
    # 14 bảng tenant_id trực tiếp.
    for t in _STRICT:
        op.execute(f"ALTER TABLE {t} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {t} "
            f"USING (tenant_id = {_T}) "
            f"WITH CHECK (tenant_id = {_T})"
        )

    # users — permissive-when-empty (login/refresh đọc khi GUC rỗng).
    op.execute("ALTER TABLE users ENABLE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON users "
        f"USING ({_T} IS NULL OR tenant_id = {_T}) "
        f"WITH CHECK ({_T} IS NULL OR tenant_id = {_T})"
    )

    # bảng con — gián tiếp qua parent.tenant_id.
    for child, parent, fk in _CHILD:
        op.execute(f"ALTER TABLE {child} ENABLE ROW LEVEL SECURITY")
        op.execute(
            f"CREATE POLICY tenant_isolation ON {child} "
            f"USING (EXISTS (SELECT 1 FROM {parent} p "
            f"               WHERE p.id = {child}.{fk} AND p.tenant_id = {_T})) "
            f"WITH CHECK (EXISTS (SELECT 1 FROM {parent} p "
            f"               WHERE p.id = {child}.{fk} AND p.tenant_id = {_T}))"
        )


def downgrade() -> None:
    for child, _parent, _fk in _CHILD:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {child}")
        op.execute(f"ALTER TABLE {child} DISABLE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON users")
    op.execute("ALTER TABLE users DISABLE ROW LEVEL SECURITY")
    for t in _STRICT:
        op.execute(f"DROP POLICY IF EXISTS tenant_isolation ON {t}")
        op.execute(f"ALTER TABLE {t} DISABLE ROW LEVEL SECURITY")
