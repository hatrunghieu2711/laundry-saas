"""order_code sequence PER-TENANT — đổi tên kèm tenant_id (giữ nguyên giá trị)

BUG: tên sequence order_code chỉ theo branch.code (order_code_seq_b1) → mọi CN "B1"
của MỌI tenant dùng CHUNG 1 sequence → số đơn nhảy giữa các tenant. FIX: tên kèm
tenant_id hex → mỗi tenant đếm độc lập từ 1.

⚠️ VÙNG TÀI CHÍNH + 2H ĐANG CHẠY (B1=69, B2 chưa gọi). uq_orders_tenant_order_code
chặn trùng → TUYỆT ĐỐI không reset số. ALTER SEQUENCE RENAME bảo toàn last_value/
is_called/GRANT (cùng object) → 2H B1 giữ 69 (đơn kế 01-00070), B2 giữ is_called=f.

Thứ tự upgrade: (a) CRE­ATE OR REPLACE app_create_order_seq với regex MỚI (regex cũ
sẽ CHẶN tên mới) → (b) rename sequence hiện có theo branches.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-06-22
"""
from collections.abc import Sequence

from alembic import op

revision: str = "c9d0e1f2a3b4"
down_revision: str | None = "b8c9d0e1f2a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _func(regex: str) -> str:
    """app_create_order_seq (SECURITY DEFINER) với regex validate tên truyền vào."""
    return f"""
CREATE OR REPLACE FUNCTION app_create_order_seq(seq_name text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $func$
BEGIN
  IF seq_name !~ '{regex}' THEN
    RAISE EXCEPTION 'invalid sequence name: %', seq_name;
  END IF;
  EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I START 1', seq_name);
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'laundry_app') THEN
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I TO laundry_app', seq_name);
  END IF;
END;
$func$;
"""


_REGEX_NEW = r"^order_code_seq_[0-9a-f]{32}_b[0-9]+$"
_REGEX_OLD = r"^order_code_seq_b[0-9]+$"

# Rename: oldn=order_code_seq_{code} → newn=order_code_seq_{tenant_hex}_{code}.
# Chỉ rename khi oldn TỒN TẠI và newn CHƯA có (idempotent, không đè).
_RENAME_FWD = """
DO $$
DECLARE r record; oldn text; newn text;
BEGIN
  FOR r IN SELECT code, tenant_id FROM branches LOOP
    oldn := 'order_code_seq_' || lower(r.code);
    newn := 'order_code_seq_' || replace(r.tenant_id::text, '-', '') || '_' || lower(r.code);
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = oldn)
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = newn) THEN
      EXECUTE format('ALTER SEQUENCE %I RENAME TO %I', oldn, newn);
    END IF;
  END LOOP;
END $$;
"""

# Rename ngược (downgrade). ⚠️ CHỈ an toàn khi 1 tenant: 2 tenant cùng code → cùng
# oldn 'order_code_seq_b1' → guard NOT EXISTS oldn chỉ rename được cái đầu (best-effort).
_RENAME_BACK = """
DO $$
DECLARE r record; oldn text; newn text;
BEGIN
  FOR r IN SELECT code, tenant_id FROM branches LOOP
    oldn := 'order_code_seq_' || lower(r.code);
    newn := 'order_code_seq_' || replace(r.tenant_id::text, '-', '') || '_' || lower(r.code);
    IF EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = newn)
       AND NOT EXISTS (SELECT 1 FROM pg_class WHERE relkind = 'S' AND relname = oldn) THEN
      EXECUTE format('ALTER SEQUENCE %I RENAME TO %I', newn, oldn);
    END IF;
  END LOOP;
END $$;
"""


def upgrade() -> None:
    # (a) Function nhận tên MỚI trước (regex cũ sẽ chặn tên mới khi create_branch chạy).
    op.execute(_func(_REGEX_NEW))
    # (b) Đổi tên sequence hiện có — giữ nguyên giá trị (ALTER RENAME, KHÔNG setval).
    op.execute(_RENAME_FWD)


def downgrade() -> None:
    op.execute(_RENAME_BACK)
    op.execute(_func(_REGEX_OLD))
