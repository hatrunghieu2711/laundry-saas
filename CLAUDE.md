# CLAUDE.md — Laundry SaaS

## Tổng quan dự án

Nền tảng SaaS quản lý tài chính và vận hành cho chuỗi giặt ủi đa chi nhánh.
Đây KHÔNG phải POS system — đây là "Financial Control and Operations Platform".

Mục tiêu số 1: chống thất thoát tiền mặt. Chủ chuỗi giám sát toàn bộ dòng tiền,
ca làm việc, và trạng thái đơn từ xa mà không cần có mặt tại cửa hàng.

Khách hàng triển khai đầu tiên: Giặt Ủi 2H (3 chi nhánh, Nha Trang).
Mục tiêu dài hạn: bán SaaS subscription cho 50–100 branch.

## Tech stack

- Backend: FastAPI + SQLAlchemy 2.0 ASYNC + asyncpg + PostgreSQL 16 + Alembic + Redis
- Frontend: React + Vite + vite-plugin-pwa (POS PWA, Shipper PWA, Admin Dashboard)
- Auth: JWT access token (30 phút) + refresh token stateful trong DB (7 ngày),
  cookie httpOnly + Secure + SameSite=Strict, CSRF Double Submit (X-CSRF-Token)
- Deploy: Docker Compose tại /opt/laundry-saas/, nginx reverse proxy trên host
- Kiến trúc: MONOLITH. Không microservices. Không Kubernetes.

## QUY TẮC TÀI CHÍNH — KHÔNG BAO GIỜ VI PHẠM

1. Bảng `payments` là IMMUTABLE: chỉ INSERT. Không bao giờ UPDATE hoặc DELETE
   bất kỳ dòng nào. Sửa sai = INSERT giao dịch đối ứng mới.
   Enforce ở DB level bằng trigger `payments_no_update_delete` (BEFORE UPDATE OR
   DELETE → RAISE EXCEPTION), không chỉ ở tầng service. (Migration 4f8dd4619d6c.)
   Lưu ý: trigger row-level KHÔNG chặn `TRUNCATE` — chỉ dùng TRUNCATE cho dữ liệu test.
2. Mọi payment PHẢI có `shift_id` trỏ tới một shift đang OPEN tại thời điểm tạo.
   Không có ngoại lệ.
3. Refund là giao dịch âm (amount < 0), không phải sửa giao dịch cũ.
4. Doanh thu LUÔN được tính từ bảng `payments` (SUM), không lưu sẵn ở đâu khác.
   Ngoại lệ duy nhất: các cột aggregate trên `shifts` được tính MỘT LẦN lúc đóng ca
   (ca đã đóng là immutable nên con số đó vĩnh viễn đúng).
5. Nguyên tắc ghi nhận: "Ai thu tiền, người đó ghi nhận" — payment thuộc shift
   của người thu, kể cả COD (COD vào shift của shipper).

## QUY TẮC SHIFT

1. Mỗi branch chỉ có TỐI ĐA MỘT shift đang open — enforce bằng partial unique
   index ở DB level, không chỉ ở code.
2. Shift đã CLOSED là bất biến: không sửa, không reopen, không thêm payment.
3. Sai sót của ca cũ → ghi giao dịch điều chỉnh (adjustment) vào ca hiện tại,
   kèm `reason` bắt buộc.
4. Đóng ca = reconciliation: hệ thống tính `closing_cash_expected`
   (= opening_cash + SUM(cash payments của ca)), nhân viên nhập
   `closing_cash_actual`, hệ thống lưu `cash_difference = actual - expected`
   và tính sẵn các cột aggregate. Lệch két vượt ngưỡng → cảnh báo owner qua Telegram.

## QUY TẮC MULTI-TENANT

1. Mọi bảng nghiệp vụ có `tenant_id`. Bảng vận hành có thêm `branch_id`.
2. MỌI query phải filter `tenant_id` ở tầng repository/service — lấy từ JWT,
   không bao giờ tin tenant_id từ request body.
3. Index luôn composite bắt đầu bằng tenant: `(tenant_id, branch_id, created_at)`.
4. Shared schema, một database. Không schema-per-tenant.

## QUY TẮC ORDER

1. Trạng thái: created → washing → drying → ready → delivered → completed.
   `cancelled` được phép từ mọi trạng thái trước delivered.
2. KHÔNG cho nhảy lùi trạng thái. `completed` và `cancelled` là trạng thái
   cuối — đơn đã vào đó thì đóng vĩnh viễn, không reopen.
3. Không sửa `total_amount` sau khi đơn đã có payment. Điều chỉnh giá =
   giao dịch adjustment trong payments.
4. DELETE order = chuyển sang `cancelled` (soft). Không xóa cứng.
5. `order_code`: prefix theo branch + sequence riêng per branch, dạng `B1-00001`.
   Sinh bằng PostgreSQL sequence (một sequence mỗi branch, tạo khi tạo branch) —
   KHÔNG dùng MAX()+1 (race condition).

## DATABASE SCHEMA (baseline)

Quy ước chung: mọi ID là UUID, mọi timestamp là UTC (timestamptz),
mọi bảng có created_at; bảng mutable có updated_at.

### tenants
- id UUID PK, name, slug (unique), status, created_at, updated_at

### branches
- id UUID PK, tenant_id FK, name, address, phone, code (vd "B1", dùng cho order_code prefix),
  status, created_at, updated_at
- Soft delete qua status — KHÔNG xóa cứng (có lịch sử payment).
- Index: (tenant_id)

### users
- id UUID PK, tenant_id FK, branch_id FK nullable, role, full_name, phone,
  email nullable, password_hash, status, created_at, updated_at
- role: owner | manager | staff | shipper
- Soft delete qua status.
- Unique: (tenant_id, phone). Index: (tenant_id, branch_id)

### refresh_tokens
- id UUID PK, user_id FK, token_hash, expires_at, revoked_at nullable, created_at
- Scheduler dọn token hết hạn hằng ngày 03:00.

### customers
- id UUID PK, tenant_id FK, full_name, phone nullable, email nullable, notes, created_at
- phone KHÔNG unique (khách vãng lai, số dùng chung). Index: (tenant_id, phone)

### shifts
- id UUID PK, tenant_id, branch_id, opened_by FK users, closed_by FK users nullable
- opening_cash NUMERIC(14,0)
- closing_cash_expected NUMERIC(14,0) nullable  ← tính lúc đóng ca
- closing_cash_actual NUMERIC(14,0) nullable    ← nhân viên nhập
- cash_difference NUMERIC(14,0) nullable        ← actual - expected
- total_cash, total_transfer, total_qr, total_cod NUMERIC(14,0) nullable ← aggregate lúc đóng ca
- orders_count INT nullable
- status: open | closed
- opened_at, closed_at nullable, created_at
- PARTIAL UNIQUE INDEX: CREATE UNIQUE INDEX one_open_shift_per_branch
  ON shifts (branch_id) WHERE status = 'open';
- Index: (tenant_id, branch_id, opened_at), (branch_id, status)

### orders
- id UUID PK, tenant_id, branch_id, customer_id FK nullable, order_code,
  total_amount NUMERIC(14,0), payment_status, order_status, notes,
  created_by FK users, created_at, updated_at
- payment_status: unpaid | partial | paid | refunded | debt
- order_status: created | washing | drying | ready | delivered | completed | cancelled
- Unique: (tenant_id, order_code)
- Index: (tenant_id, branch_id, created_at), (tenant_id, order_status), (customer_id)

### order_items
- id UUID PK, order_id FK, service_name, quantity NUMERIC(8,2), unit_price NUMERIC(14,0),
  subtotal NUMERIC(14,0), created_at
- Index: (order_id)

### payments  ← IMMUTABLE
- id UUID PK, tenant_id, branch_id, order_id FK, shift_id FK NOT NULL,
  amount NUMERIC(14,0)  ← âm cho refund/cancel
- payment_method: cash | transfer | qr | cod
- transaction_type: payment | refund | adjustment | debt | resolve_debt | cancel_paid
- reason TEXT nullable — BẮT BUỘC (validate ở service) với refund/adjustment/cancel_paid
- reference_payment_id FK nullable (trỏ giao dịch gốc khi refund/cancel)
- created_by FK users, created_at
- Quy ước dấu (sign): + payment/resolve_debt/adjustment dương; − refund/cancel_paid;
  debt có amount = 0 trong dòng tiền (ghi nợ, chưa thu).
- Index: (tenant_id, branch_id, created_at), (shift_id), (order_id)

### deliveries
- id UUID PK, tenant_id, branch_id, order_id FK, shipper_id FK users,
  delivery_status, cod_amount NUMERIC(14,0) nullable, assigned_at, completed_at nullable
- delivery_status: assigned | picked_up | delivering | delivered | failed
- COD: khi shipper xác nhận đã thu, tạo payment (method=cod) vào SHIFT CỦA SHIPPER.
- Index: (shipper_id, delivery_status), (order_id)

### order_tracking_logs
- id UUID PK, order_id FK, status, changed_by FK users nullable, created_at
- Ghi MỌI lần đổi order_status. Nguồn dữ liệu cho trang tracking công khai.
- Index: (order_id)

### audit_logs
- id UUID PK, tenant_id, user_id, action, entity_type, entity_id,
  old_data_json JSONB, new_data_json JSONB, created_at
- Index: (tenant_id, created_at), (user_id)

### plans, subscriptions
- Tạo bảng trong baseline nhưng CHƯA viết logic — chỉ làm khi có khách ngoài đầu tiên.

KHÔNG implement trong MVP: expenses, promotions, coupons, loyalty_points,
sms_logs, notifications, inventory, machines.

## API CONVENTIONS

- Base: /api/v1. Không bao giờ break client cũ — thay đổi lớn thì lên /api/v2.
- Error format thống nhất:
  { "success": false, "message": "...", "code": "ORDER_NOT_FOUND" }
- Mọi endpoint danh sách (orders, payments, customers) PHẢI có pagination
  (limit/offset, default limit=50, max=200).
- Endpoint công khai duy nhất: GET /public/track/{order_code} — không auth,
  có rate limit theo IP (Redis), chỉ trả: order_code, status, timeline trạng thái,
  branch name. KHÔNG lộ tiền, tên khách, số điện thoại.
- /dashboard/* và /reports/* nhận filter branch_id, start_date, end_date.
- DELETE branches/users = soft delete (đổi status), không xóa dòng.

## CODING STANDARDS

- Service layer pattern: business logic trong app/services/. Router CHỈ
  validate input và gọi service. Không logic trong router.
- Async toàn bộ. Type hints toàn bộ. Pydantic v2 cho schemas.
- Mọi thay đổi schema = một Alembic migration. Không sửa DB tay.
- Tiền dùng NUMERIC, không float. VND không có số lẻ → NUMERIC(14,0).
- Không file quá ~400 dòng — tách module.
- Uvicorn chạy --workers 1 (giữ singleton cho scheduler/websocket nếu có sau này).

## TEST

- Test bắt buộc cho MỌI logic liên quan tiền: cashflow formula (parametrized),
  shift reconciliation, sign convention, scenario integration (mở ca → đơn →
  thu → refund → đóng ca → kiểm tra expected/difference/aggregates).
- Viết test TRƯỚC khi viết service cho logic tài chính.
- Chạy test: docker compose exec app sh -c "cd /code && pytest tests/ -x -q"
- Sau mỗi thay đổi code, chạy test và báo kết quả trước khi kết thúc task.

## WORKFLOW

- Commit sau mỗi task hoàn chỉnh, message tiếng Anh ngắn gọn (feat:/fix:/test:).
- Khi user chốt một quyết định nghiệp vụ mới trong phiên làm việc,
  cập nhật ngay vào file CLAUDE.md này.
- Khi sửa file mà str_replace báo NOT FOUND: đọc lại nội dung file thực tế
  trước khi thử lại, không đoán.
- Secrets (DB password, JWT secret) chỉ nằm trong .env — file .env trong
  .gitignore, không bao giờ commit.

## NỢ KỸ THUẬT ĐÃ BIẾT

- **Login phone-only chưa có tenant context.** `authenticate()` duyệt mọi user
  active có cùng `phone` trên TOÀN BỘ tenant rồi khớp password. Hiện chỉ có 1
  tenant nên an toàn. TRƯỚC KHI onboard tenant thứ 2: phải thêm tenant context
  vào login (vd tenant slug / subdomain / mã tenant), nếu không hai user khác
  tenant trùng phone + trùng password sẽ đăng nhập nhập nhằng (trả về user đầu
  tiên khớp). Xử lý trước khi mở Stage 7.
- **Sinh branch `code` bằng COUNT(*) trong tenant** (B1, B2...). Đếm cả branch đã
  soft-delete để không tái sử dụng code. Có race lý thuyết khi tạo 2 branch đồng
  thời cùng tenant (rất hiếm: chỉ owner tạo, tần suất thấp) — chấp nhận ở MVP.
- **Tên sequence order_code là lowercase**: branch code `B1` → sequence
  `order_code_seq_b1` (tránh phụ thuộc case-folding của Postgres). Stage 2 sinh
  `order_code` PHẢI dùng đúng tên này.

## ROADMAP HIỆN TẠI

- [x] Stage 1: skeleton + migration baseline + auth (login/refresh/logout/me) + CRUD tenants/branches/users
- [ ] Stage 2: shifts (open/close + reconciliation) + orders + payments + Telegram alert đóng ca
- [ ] Stage 3: POS PWA (login, mở/đóng ca, tạo đơn, thu tiền, đổi trạng thái)
- [ ] Stage 4: pilot 1 branch Giặt Ủi 2H (chạy song song sổ tay 2 tuần)
- [ ] Stage 5: rollout 3 branch + Admin Dashboard + QR tracking công khai
- [ ] Stage 6: Delivery module + COD reconciliation + cron (backup/healthcheck/ssl)
- [ ] Stage 7+: Public API, subscriptions — chỉ khi có khách ngoài thật
