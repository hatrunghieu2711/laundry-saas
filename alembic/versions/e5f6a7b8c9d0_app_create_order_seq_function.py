"""app_create_order_seq function (RLS R2 — sequence Cách B)

Đưa function tạo order_code sequence (SECURITY DEFINER) vào MIGRATION để: (a) DB test
có function (conftest dựng test DB bằng migration), (b) prod build mới tái lập được
(trước đây function chỉ tồn tại do chạy tay script R1 → không reproducible).

Function chạy bằng OWNER → role app (laundry_app, non-owner) tạo được sequence mà
KHÔNG cần CREATE ON SCHEMA. GRANT cho laundry_app được BỌC `IF EXISTS` để migration
chạy được cả trên cluster CHƯA có role app (vd CI sạch).

Revision ID: e5f6a7b8c9d0
Revises: d4f5a6b7c8e9
Create Date: 2026-06-21
"""
from collections.abc import Sequence

from alembic import op

revision: str = "e5f6a7b8c9d0"
down_revision: str | None = "d4f5a6b7c8e9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_FUNC = r"""
CREATE OR REPLACE FUNCTION app_create_order_seq(seq_name text)
RETURNS void
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $func$
BEGIN
  IF seq_name !~ '^order_code_seq_b[0-9]+$' THEN
    RAISE EXCEPTION 'invalid sequence name: %', seq_name;
  END IF;
  EXECUTE format('CREATE SEQUENCE IF NOT EXISTS %I START 1', seq_name);
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'laundry_app') THEN
    EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I TO laundry_app', seq_name);
  END IF;
END;
$func$;
"""

_GRANT_EXEC = """
DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'laundry_app') THEN
    GRANT EXECUTE ON FUNCTION app_create_order_seq(text) TO laundry_app;
  END IF;
END $$;
"""


def upgrade() -> None:
    op.execute(_FUNC)
    op.execute("REVOKE ALL ON FUNCTION app_create_order_seq(text) FROM PUBLIC")
    op.execute(_GRANT_EXEC)


def downgrade() -> None:
    op.execute("DROP FUNCTION IF EXISTS app_create_order_seq(text)")
