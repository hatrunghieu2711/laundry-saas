-- ════════════════════════════════════════════════════════════════════════════
-- RLS — BƯỚC R1: tạo role DB riêng cho app (non-superuser, non-owner)
-- ════════════════════════════════════════════════════════════════════════════
-- MỤC ĐÍCH: để RLS (bật ở R3) CÓ HIỆU LỰC. Hiện app connect bằng `laundry`
-- (= POSTGRES_USER = SUPERUSER + OWNER mọi bảng) → superuser/owner BỎ QUA RLS.
-- Sau R1: APP connect bằng `laundry_app` (bị RLS chặn ở R3); MIGRATION vẫn dùng
-- `laundry` (owner → bypass → migrate không vướng policy).
--
-- ⚠️ BƯỚC NÀY CHƯA BẬT RLS, CHƯA CÓ POLICY. Chỉ tạo role + cấp quyền CRUD.
--    Lúc này laundry_app vẫn THẤY HẾT data (chưa có policy) — đúng như mong đợi.
--
-- CHẠY BẰNG: owner/superuser `laundry`. Vd:
--   docker compose exec postgres psql -U laundry -d laundry -f /path/R1_create_app_role.sql
--   (hoặc psql "postgresql://laundry:<pw>@localhost:5432/laundry" -f ...)
--
-- ⚠️ TRƯỚC KHI CHẠY:
--   1) Đặt mật khẩu mạnh ở dòng CREATE ROLE (thay __SET_STRONG_PASSWORD__).
--      Tránh ký tự reserved của URL (@ : / ? # %) để khỏi phải URL-encode trong DSN;
--      hoặc nếu có thì URL-encode khi đưa vào DATABASE_URL.
--   2) Với DB TEST (laundry_test): chạy LẠI file này nhưng đổi tên DB ở lệnh
--      GRANT CONNECT ON DATABASE bên dưới (laundry → laundry_test).
-- ════════════════════════════════════════════════════════════════════════════

\set ON_ERROR_STOP on

-- ── 1) Tạo role app (idempotent) ────────────────────────────────────────────
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'laundry_app') THEN
    CREATE ROLE laundry_app LOGIN PASSWORD '__SET_STRONG_PASSWORD__'
      NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS NOREPLICATION;
  END IF;
END $$;

-- ── 2) Kết nối + schema ─────────────────────────────────────────────────────
GRANT CONNECT ON DATABASE laundry TO laundry_app;   -- ⚠️ đổi 'laundry' → 'laundry_test' cho DB test
GRANT USAGE ON SCHEMA public TO laundry_app;

-- ── 3) CRUD trên BẢNG hiện có ───────────────────────────────────────────────
-- App đọc/ghi MỌI bảng nghiệp vụ (kể cả tenants: get_tenant_by_slug + update_tenant).
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA public TO laundry_app;

-- alembic_version: app KHÔNG được ghi (chỉ migration/owner đụng). Đọc thôi cho an toàn.
REVOKE ALL ON TABLE alembic_version FROM laundry_app;
GRANT SELECT ON TABLE alembic_version TO laundry_app;

-- ── 4) SEQUENCE hiện có (nextval cho order_code: order_service.py:235) ───────
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO laundry_app;

-- ── 5) DEFAULT PRIVILEGES — bảng/sequence TƯƠNG LAI do owner (laundry) tạo ───
-- Migration sau tạo bảng/sequence mới (chạy bằng laundry) → laundry_app TỰ có quyền,
-- không phải GRANT lại từng lần. KEY theo ROLE TẠO object = laundry.
ALTER DEFAULT PRIVILEGES FOR ROLE laundry IN SCHEMA public
  GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO laundry_app;
ALTER DEFAULT PRIVILEGES FOR ROLE laundry IN SCHEMA public
  GRANT USAGE, SELECT ON SEQUENCES TO laundry_app;

-- ════════════════════════════════════════════════════════════════════════════
-- 6) VỤ "CREATE SEQUENCE RUNTIME" (branch_service.py:126) — CHỌN 1 TRONG 2
-- ════════════════════════════════════════════════════════════════════════════
-- Khi tạo CHI NHÁNH, app chạy CREATE SEQUENCE order_code_seq_<code>. Role app
-- (non-owner) MẶC ĐỊNH không tạo được sequence → tạo branch sẽ 500. 2 cách:

-- ── CÁCH A (interim, KHÔNG sửa code) — cấp quyền tạo object trong schema ─────
-- Đơn giản, chạy ngay; nhưng RỘNG (app tạo được object bất kỳ trong public).
-- Vẫn an toàn isolation (NOBYPASSRLS giữ nguyên). Nên siết về Cách B ở R2.
--   GRANT CREATE ON SCHEMA public TO laundry_app;

-- ── CÁCH B (KHUYẾN NGHỊ, cần đổi 1 dòng code ở R2) — function SECURITY DEFINER
-- Function chạy bằng OWNER (laundry) → tạo sequence + tự GRANT cho app; role app
-- KHÔNG cần CREATE ON SCHEMA. Validate tên (khớp _SEQ_RE) chống injection.
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
  EXECUTE format('GRANT USAGE, SELECT ON SEQUENCE %I TO laundry_app', seq_name);
END;
$func$;
REVOKE ALL ON FUNCTION app_create_order_seq(text) FROM PUBLIC;
GRANT EXECUTE ON FUNCTION app_create_order_seq(text) TO laundry_app;
-- → R2: đổi branch_service.py:126 từ
--      await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{_sequence_name(code)}" START 1'))
--    thành
--      await db.execute(text("SELECT app_create_order_seq(:n)"), {"n": _sequence_name(code)})
--    (Tới khi đổi xong, nếu vẫn dùng CREATE SEQUENCE trực tiếp thì phải bật CÁCH A.)

-- ── 7) KIỂM THUỘC TÍNH ROLE (mong đợi: tất cả false) ────────────────────────
-- SELECT rolname, rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
--   FROM pg_roles WHERE rolname = 'laundry_app';
