-- ════════════════════════════════════════════════════════════════════════════
-- RLS R1 — SMOKE TEST: verify role `laundry_app` connect được + đủ quyền CRUD.
-- ════════════════════════════════════════════════════════════════════════════
-- CHẠY BẰNG laundry_app (sau khi đã chạy R1_create_app_role.sql bằng owner):
--   psql "postgresql://laundry_app:<APP_PW>@localhost:5432/laundry" -f R1_smoke_test.sql
-- LƯU Ý: R1 CHƯA bật RLS → laundry_app THẤY HẾT data (đúng). Chỉ kiểm QUYỀN, không kiểm cách ly.
-- KHÔNG để lại dữ liệu: phần ghi nằm trong BEGIN ... ROLLBACK.
-- ════════════════════════════════════════════════════════════════════════════

\set ON_ERROR_STOP on

-- 1) Đúng role + KHÔNG có đặc quyền bypass (mong đợi: f | f | f | f)
SELECT current_user,
       rolsuper, rolbypassrls, rolcreatedb, rolcreaterole
  FROM pg_roles WHERE rolname = current_user;

-- 2) Đọc được các bảng chính
SELECT 'tenants'  AS tbl, count(*) FROM tenants
UNION ALL SELECT 'orders',   count(*) FROM orders
UNION ALL SELECT 'payments', count(*) FROM payments
UNION ALL SELECT 'shifts',   count(*) FROM shifts;

-- 3) Có quyền GHI (UPDATE/INSERT/DELETE) — kiểm bằng WHERE false (0 row) rồi ROLLBACK.
BEGIN;
  UPDATE tenants  SET name = name        WHERE false;  -- quyền UPDATE
  DELETE FROM orders                     WHERE false;  -- quyền DELETE
  -- quyền INSERT: thử chèn rồi rollback (dùng tenant_id giả, sẽ rollback toàn bộ)
  -- (bỏ comment nếu muốn kiểm INSERT; cần 1 tenant_id hợp lệ)
  -- INSERT INTO customers (tenant_id, full_name, phone)
  --   VALUES ((SELECT id FROM tenants LIMIT 1), 'smoke', '0000');
ROLLBACK;

-- 4) (TÙY) nextval order_code — CHỈ nếu đã có sequence; nextval KHÔNG rollback được
--    nên bỏ qua trên prod (sẽ nhảy 1 số). Kiểm trên DB test thì OK:
-- SELECT nextval('order_code_seq_b1');

\echo '== R1 smoke OK: laundry_app connect + đọc + có quyền ghi (chưa bật RLS) =='
