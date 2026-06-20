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
6. **Sign convention (chốt Stage 2c):** client gửi `amount` là MAGNITUDE (số
   dương); service áp dấu theo `transaction_type` rồi LƯU:
   payment/resolve_debt/adjustment → +mag; refund/cancel_paid → −mag; debt → 0.
   Gửi `amount <= 0` cho type khác debt → **422 INVALID_AMOUNT** (KHÔNG tự đảo
   dấu — reject để lộ lỗi client). branch/tenant/shift của payment lấy từ order
   + ca đang mở, KHÔNG nhận từ client.
7. **payment_status (chốt Stage 2c)** tính lại sau MỖI payment từ
   `paid_sum = SUM(amount)` mọi payment của đơn, theo THỨ TỰ ƯU TIÊN (match đầu
   tiên thắng): (1) `paid` nếu total>0 và paid_sum ≥ total; (2) `partial` nếu
   0 < paid_sum < total; (3) `refunded` nếu paid_sum ≤ 0 và có refund/cancel_paid;
   (4) `debt` nếu có dòng debt chưa có resolve_debt; (5) `unpaid`.
8. **2H KHÔNG có THU MỘT PHẦN (chốt Stage 6.6.4).** "Thu trước" = thu ĐỦ 100% =
   total_amount ngay khi tạo đơn; "Thu sau" = chưa thu gì (thu đủ khi giao). KHÔNG
   có ô nhập số tiền tùy ý ở màn tạo đơn. POST /orders nhận `prepay: bool` +
   `payment_method` → server tự ghi payment = ĐÚNG total_amount (KHÔNG nhận số tiền
   từ client → không sai sổ). prepay cần ca mở (409 NO_OPEN_SHIFT trước khi tạo đơn,
   tránh đơn mồ côi). Trạng thái `partial` về lý thuyết vẫn tồn tại nhưng luồng tạo
   đơn 2H không sinh ra nó.

## QUY TẮC SHIFT

1. Mỗi branch chỉ có TỐI ĐA MỘT shift đang open — enforce bằng partial unique
   index ở DB level, không chỉ ở code.
2. Shift đã CLOSED là bất biến: không sửa, không reopen, không thêm payment.
3. Sai sót của ca cũ → ghi giao dịch điều chỉnh (adjustment) vào ca hiện tại,
   kèm `reason` bắt buộc.
4. Đóng ca = reconciliation: hệ thống tính `closing_cash_expected`
   (= opening_cash + SUM(cash payments của ca) + SUM(thu tiền mặt) − SUM(chi tiền
   mặt) sổ quỹ — Stage 4.2), nhân viên nhập `closing_cash_actual`, hệ thống lưu
   `cash_difference = actual - expected` và tính sẵn các cột aggregate (gồm
   total_income/total_expense tiền mặt). Lệch két vượt ngưỡng → cảnh báo owner qua
   Telegram (message kèm dòng thu/chi tiền mặt ngoài dịch vụ nếu có).
5. **Chỉ số REALTIME ca đang mở (Stage 6.1): GET /shifts/{id}/summary** →
   cash_in_drawer (= ĐÚNG công thức expected lúc đóng ca), transfer_total (CK+QR),
   total_collected (mọi payment cash+transfer+qr theo shift_id), shift_revenue
   (SUM total_amount đơn TẠO trong ca: created_at ∈ ca + cùng branch + trừ cancelled),
   order_count (đơn tạo trong ca). **PHÂN BIỆT KẾ TOÁN (KHÔNG phải bug khi lệch):**
   total_collected = TIỀN THU theo ca THU (gồm đơn nợ ca TRƯỚC thu ca này — "ai thu
   người đó ghi nhận"); shift_revenue = DOANH THU theo ca TẠO đơn (kể cả đơn còn nợ
   chưa thu). Đơn nợ qua ca → 2 số lệch là đúng.

## QUY TẮC MULTI-TENANT

1. Mọi bảng nghiệp vụ có `tenant_id`. Bảng vận hành có thêm `branch_id`.
2. MỌI query phải filter `tenant_id` ở tầng repository/service — lấy từ JWT,
   không bao giờ tin tenant_id từ request body.
3. Index luôn composite bắt đầu bằng tenant: `(tenant_id, branch_id, created_at)`.
4. Shared schema, một database. Không schema-per-tenant.

## QUY TẮC ORDER

1. Trạng thái: created → washing → drying → ready → delivered → completed.
   `cancelled` được phép từ mọi trạng thái trước delivered.
2. **State machine (cập nhật Stage 3.9 — cho LÙI có kiểm soát):**
   - Tiến: đúng 1 bước theo chuỗi trên.
   - LÙI trong nhóm xử lý tại tiệm `[created, washing, drying, ready]`: cho lùi
     về BẤT KỲ bước trước trong nhóm (vd ready→created một phát). Nhảy tiến cách
     bước (vd created→ready) vẫn cấm → 409 INVALID_STATUS_TRANSITION.
   - `delivered → ready`: CHỈ khi `payment_status='unpaid'`. Nếu paid/partial/
     debt → 409 **CANNOT_REVERT_PAID_DELIVERY** ("Không thể lùi đơn đã thu tiền").
   - `completed`/`cancelled`: KHÓA vĩnh viễn — mọi chuyển đi → 409 **ORDER_CLOSED**.
   - MỌI lần đổi trạng thái (tiến lẫn lùi) ghi `order_tracking_logs`
     (status, changed_by, created_at) để truy vết ai lùi.
3. Không sửa `total_amount` sau khi đơn đã có payment. Điều chỉnh giá =
   giao dịch adjustment trong payments.
4. DELETE order = chuyển sang `cancelled` (soft). Không xóa cứng.
5. `order_code`: `{branch.order_prefix}-{số}` (Stage 5.1; trước đây prefix = branch
   `code`). Sinh bằng PostgreSQL sequence (một sequence mỗi branch, keyed theo
   `code` BẤT BIẾN — KHÔNG theo prefix; tạo khi tạo branch) — KHÔNG dùng MAX()+1
   (race condition). Số tối thiểu 5 chữ số (`00001`), TỰ NỚI 6/7… chữ số khi vượt
   99999/999999 (`:05d`) — KHÔNG reset, KHÔNG đụng trần. Owner đổi `order_prefix`
   chỉ ảnh hưởng đơn MỚI; đơn cũ giữ mã đã in.

## DATABASE SCHEMA (baseline)

Quy ước chung: mọi ID là UUID, mọi timestamp là UTC (timestamptz),
mọi bảng có created_at; bảng mutable có updated_at.

### tenants
- id UUID PK, name, slug (unique), status, created_at, updated_at

### branches
- id UUID PK, tenant_id FK, name, address, phone, code (vd "B1", do hệ thống sinh —
  dùng cho TÊN SEQUENCE order_code, BẤT BIẾN), order_prefix (Stage 5.1, migration
  a1b2c3d4e5f6), status, created_at, updated_at
- `order_prefix` String(16): tiền tố HIỂN THỊ của order_code (vd "CH1", "1", "B1"),
  owner tùy chỉnh. Mặc định = `code` lúc tạo. Validate: chỉ chữ/số (`^[A-Za-z0-9]+$`),
  ≤16 ký tự, không khoảng trắng/ký tự đặc biệt (sai → 422 INVALID_PREFIX). UNIQUE
  `(tenant_id, order_prefix)` (gồm cả branch soft-delete — order_code không tái dùng;
  trùng → 422 PREFIX_TAKEN). Đổi prefix CHỈ ảnh hưởng đơn MỚI.
- Soft delete qua status — KHÔNG xóa cứng (có lịch sử payment).
- Index: (tenant_id), UNIQUE (tenant_id, order_prefix)

### users
- id UUID PK, tenant_id FK, branch_id FK nullable, role, full_name, phone,
  email nullable, password_hash, status, created_at, updated_at
- role: owner | manager | staff | shipper
- status: active | suspended (khóa, Stage 5.5) | inactive (soft-delete). Login +
  get_current_user CHỈ chấp nhận `active` → suspended/inactive đều bị từ chối.
- **`phone` là ĐỊNH DANH ĐĂNG NHẬP (username)** — KHÔNG bắt buộc là số thật; tài
  khoản theo CA hợp lệ (vd phone="nv_ca_sang", full_name="NV ca sáng - Trần Phú").
- Soft delete qua status. Unique: (tenant_id, phone). Index: (tenant_id, branch_id)
- Quản lý (Stage 5.5): GET /users (owner: cả tenant; manager: chỉ branch mình —
  list kèm transient `branch_name` + `in_open_shift`=đang là người mở 1 ca open),
  POST /users, PATCH /users/{id} (sửa role/branch/tên), POST /users/{id}/
  reset-password, PATCH /users/{id}/status (active|suspended), DELETE=soft.
  Phân quyền: owner mọi user; manager chỉ staff/shipper branch mình; KHÔNG ai sửa
  role owner; KHÔNG tự khóa mình (409 CANNOT_SUSPEND_SELF) / tự xóa mình.

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
- total_income, total_expense NUMERIC(14,0) nullable ← thu/chi TIỀN MẶT sổ quỹ, tính
  lúc đóng ca (Stage 4.2, migration a4b5c6d7e8f9). CHỈ phần tiền mặt (ảnh hưởng két);
  thu/chi qua transfer/qr KHÔNG gộp vào hai cột này.
- orders_count INT nullable
- handover_to_owner, cash_left_for_next NUMERIC(14,0) nullable (Stage 6.2, migration
  e9f0a1b2c3d4): RÚT TIỀN NỘP CHỦ khi đóng ca. handover_to_owner = tiền ra khỏi két
  SAU đối soát (KHÔNG vào expected, KHÔNG phải chi phí, KHÔNG ảnh hưởng doanh thu).
  cash_left_for_next = closing_cash_actual − handover_to_owner → gợi ý đầu ca sau.
  Validate handover ≤ closing_cash_actual (422 HANDOVER_EXCEEDS_CASH).
- status: open | closed
- opened_at, closed_at nullable, created_at
- closing_cash_expected = opening_cash + SUM(cash payments) + total_income − total_expense
  (Stage 4.2: cộng thu tiền mặt, trừ chi tiền mặt sổ quỹ; xem cash_transactions).
  **handover_to_owner KHÔNG nằm trong công thức expected** (rút từ tiền thực đếm đã khớp).
- Endpoints (Stage 6.1/6.2): GET /shifts/{id}/summary (realtime), GET
  /shifts/opening-suggestion (= cash_left_for_next ca đóng gần nhất cùng branch;
  nhân viên đếm lại), POST /shifts/{id}/close nhận handover_to_owner. Báo cáo nộp
  chủ: GET /reports/owner-handover (owner) — liệt kê khoản nộp chủ theo ca đã đóng.
- Báo cáo tổng cho chủ (Stage 6.3): GET /reports/owner-summary (owner) — params
  from_date/to_date/branch_id (thiếu branch_id = tất cả CN). Trả 4 nhóm trong khoảng:
  (a) revenue {total, by_day[], by_branch[]} = SUM(orders.total_amount) đơn TẠO trong
  khoảng, LOẠI order_status='cancelled'; by_branch chỉ điền khi xem tất cả CN.
  (b) handover = dùng lại owner_handover_report (ca đóng trong khoảng, handover>0).
  (c) cash_diff {total(net có dấu), count(ca lệch), matched_count(ca khớp), rows[]} —
  ca ĐÓNG trong khoảng; CHỈ liệt kê ca cash_difference≠0 (cảnh báo thất thoát), ca
  khớp chỉ ĐẾM. (d) unpaid {total_outstanding, order_count} = đơn TẠO trong khoảng có
  payment_status IN (unpaid,partial,debt), còn nợ = total_amount − SUM(payments).
  QUYẾT ĐỊNH: nợ tính theo đơn TẠO trong khoảng (nhất quán filter ngày+CN), giá trị
  nợ là tới HIỆN TẠI. Ngày theo UTC (MVP). Read-only, không migration.
- PARTIAL UNIQUE INDEX: CREATE UNIQUE INDEX one_open_shift_per_branch
  ON shifts (branch_id) WHERE status = 'open';
- Index: (tenant_id, branch_id, opened_at), (branch_id, status)

### orders
- id UUID PK, tenant_id, branch_id, customer_id FK nullable, order_code,
  total_amount NUMERIC(14,0), payment_status, order_status,
  pickup_at timestamptz NOT NULL (giờ hẹn giao, Stage 3.7A, migration c3a1f9d2b7e4),
  notes, created_by FK users, created_at, updated_at
- **subtotal, surcharge_amount, discount_amount NUMERIC(14,0) + surcharge_reason,
  discount_reason TEXT (Stage 5.4, migration c7d8e9f0a1b2):** phụ thu/giảm vào TIỀN
  THẬT. `total_amount = subtotal + surcharge_amount − discount_amount`. SNAPSHOT lúc
  tạo đơn (bất biến như giá món). total_amount VẪN là tiền thật (vào payment, doanh
  thu, đối soát ca — KHÔNG display-only). Đơn cũ backfill subtotal = total_amount.
- pickup_at: BẮT BUỘC khi tạo đơn, service validate phải > now (422
  PICKUP_AT_IN_PAST). PUT sửa được khi đơn chưa completed/cancelled (409
  ORDER_CLOSED nếu đã đóng). Đơn cũ migration backfill = created_at + 4h.
- payment_status: unpaid | partial | paid | refunded | debt
- order_status: created | washing | drying | ready | delivered | completed | cancelled
- Unique: (tenant_id, order_code)
- Index: (tenant_id, branch_id, created_at), (tenant_id, order_status), (customer_id)

### price_rules (Stage 5.4, migration c7d8e9f0a1b2) — quy tắc phụ thu/giảm tự áp
- id UUID PK, tenant_id FK, type (surcharge|discount), value_type (percent|fixed),
  value NUMERIC(14,2), name String(120), start_date DATE, end_date DATE,
  is_active bool, created_at, updated_at. Soft delete qua is_active. Tenant-scoped.
- Owner CRUD (POST/PUT/DELETE /price-rules). validate end>=start (422
  INVALID_DATE_RANGE), percent<=100 (422 PERCENT_TOO_HIGH) ở SERVICE (để có `code`).
- Tự áp khi tạo đơn: rule ACTIVE phủ NGÀY VN (UTC+7) hiện tại; nhiều rule cùng loại
  → lấy mới nhất (start_date, created_at desc). GET /price-rules/applicable (mọi role
  — POS điền sẵn badge "tự áp"). Index: (tenant_id, is_active), (tenant_id, type, dates).

### discount_logs (Stage 5.4, migration c7d8e9f0a1b2) — nhật ký giảm giá (append-only)
- id UUID PK, tenant_id, branch_id, order_id FK, user_id FK nullable (ai giảm),
  amount NUMERIC(14,0), reason TEXT nullable, created_at.
- Ghi khi tạo đơn có discount_amount > 0. Nguồn cho GET /reports/discounts (owner):
  tổng giảm + theo nhân viên, lọc start_date/end_date/branch_id.
- Index: (tenant_id, created_at), (tenant_id, user_id), (order_id)

### order_items
- id UUID PK, order_id FK, service_id FK nullable (→ services), service_name,
  quantity NUMERIC(8,2), unit_price NUMERIC(14,0), subtotal NUMERIC(14,0), created_at
- `service_id` để truy nguồn dòng giá; `service_name`/`unit_price`/`subtotal` là
  SNAPSHOT lúc tạo đơn — sửa bảng giá sau KHÔNG đổi giá đơn cũ.
- Index: (order_id)

### categories (Stage 4.3, migration b5c6d7e8f9a0) — danh mục dịch vụ
- id UUID PK, tenant_id FK, name String(64), icon String(32) nullable (emoji/tên icon),
  display_order INT, is_active bool, created_at, updated_at.
- Tách từ `services.category` text cũ thành thực thể riêng (có icon + thứ tự) để owner
  quản lý tập trung. Soft delete qua is_active. Tenant-scoped.
- Index: (tenant_id, is_active, display_order).
- CRUD /categories: owner/manager ghi (tạo/sửa/xóa-soft/PUT reorder); mọi role đọc.
  Chặn xóa danh mục còn dịch vụ ACTIVE đang dùng → 409 CATEGORY_IN_USE ("còn N dịch vụ").

### services (Stage 3.5A, migration 8824c0db78cf) — bảng giá động
- id UUID PK, tenant_id FK, name, unit (kg|cai|con|bo|luot), unit_price NUMERIC(14,0),
  pricing_type (per_unit|tier), display_order INT, is_active bool, created_at, updated_at
- category_id UUID FK nullable → categories (Stage 4.3, migration b5c6d7e8f9a0; THAY cho
  cột text `category` cũ) + is_favorite bool (Stage 3.8): gom tab màn tạo đơn; "Hay chọn"
  = is_favorite=true. ServiceOut nhúng object `category` {id,name,icon,display_order}.
- per_unit: subtotal = quantity × unit_price (vd Áo Vest 60k/cái).
- tier: bậc cân qua bảng `service_tiers` (giặt sấy 60/90/120k...).
- Soft delete qua is_active. Tenant-scoped. Index: (tenant_id, is_active, display_order)

### service_tiers (Stage 3.5A) — bậc giá của service tier
- id UUID PK, service_id FK, label (vd "≤3kg"), max_value NUMERIC(8,2) nullable,
  price NUMERIC(14,0), per_unit bool, display_order INT, created_at
- max_value = ngưỡng trên (bao gồm) của bậc; NULL = bậc overflow (vượt ngưỡng).
- per_unit=false: giá TRỌN GÓI (subtotal = price, KHÔNG nhân). per_unit=true:
  subtotal = price × quantity (vd bậc >7kg = 18k/kg).
- Index: (service_id)

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

### cash_transactions  ← IMMUTABLE (Stage 4.2, migration a4b5c6d7e8f9)
- Sổ quỹ thu-chi NGOÀI đơn hàng (mua vật tư, tiền điện, ứng lương, thu khác...).
- id UUID PK, tenant_id, branch_id, shift_id FK NOT NULL (thu/chi phải thuộc ca
  đang mở, giống payments), type (income | expense), amount NUMERIC(14,0) LUÔN
  DƯƠNG (dấu xác định bởi type — CHECK amount > 0), category String(64) NOT NULL
  (gợi ý + text tự do), note TEXT nullable, payment_method (cash | transfer | qr,
  default cash; KHÔNG có cod), created_by FK users, created_at.
- IMMUTABLE như payments: chỉ INSERT; trigger `cash_transactions_no_update_delete`
  (BEFORE UPDATE OR DELETE → RAISE). Sửa sai = ghi giao dịch đối ứng.
- branch phân giải qua scope.resolve_write_branch (owner truyền branch_id; staff
  lấy từ token). Cần ca đang OPEN tại branch → nếu không: 409 NO_OPEN_SHIFT.
  amount ≤ 0 → 422 INVALID_AMOUNT; category rỗng → 422 CATEGORY_REQUIRED.
- Endpoints: POST /cash-transactions, GET (pagination + filter shift_id/branch_id/
  type/from/to), GET /{id}. KHÔNG có UPDATE/DELETE.
- Đóng ca: SUM(income) − SUM(expense) phần TIỀN MẶT cộng/trừ vào
  closing_cash_expected; lưu shift.total_income/total_expense (xem shifts).
- Index: (tenant_id, branch_id, created_at), (shift_id)

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

### tenant_settings  (thêm ở Stage 2d, migration 50ac9ec03c5e)
- tenant_id UUID PK + FK tenants (one-to-one), telegram_bot_token,
  telegram_owner_chat_id, cash_diff_threshold NUMERIC(14,0) default 50000,
  default_turnaround_hours INT default 4 (Stage 3.8, migration d1e2f3a4b5c6),
  receipt_default_config JSONB nullable (Stage 5.10, migration d8e9f0a1b2c3 — mẫu
  phiếu MẶC ĐỊNH per-tenant cho nút Khôi phục; NULL → fallback mẫu gốc nền tảng),
  created_at, updated_at.
- Cấu hình per-tenant; chứa secret (bot token) nên tách khỏi bảng `tenants`.
- Đóng ca xong gửi Telegram cho owner (httpx async, SAU commit); lỗi gửi KHÔNG
  làm fail đóng ca. |cash_difference| > cash_diff_threshold → thêm ⚠️ LỆCH KÉT.
- Endpoints (Stage 3.8): GET /settings/pos (mọi role, chỉ field POS — turnaround,
  KHÔNG lộ secret), GET /settings (owner/manager, đầy đủ), PUT /settings (owner).
  Row settings tạo LAZY khi đọc lần đầu (server_default lo giá trị mặc định).
- default_turnaround_hours: POS gợi ý giờ hẹn giao = now(VN) + giá trị này.
- receipt_config JSONB nullable (Stage 4.1, migration f3a4b5c6d7e8; chỉ đổi shape
  JSONB qua các stage, KHÔNG cần migration mới): mẫu phiếu in per-tenant.
  - **Stage 5.6 — BILL BUILDER THEO KHỐI (thay layout cứng 2H của 5.3).** Shape:
    `{bilingual: bool, logo_url: str, blocks: [{id, type, enabled, row, col, content}]}`.
    - `bilingual`: bật/tắt tiếng Anh TOÀN bill (nhãn "vi / en" → chỉ "vi").
    - `row` (số hàng) + `col` (full | left | right): 2 khối HẸP/hàng (chia đôi 80mm).
    - `type` ∈ logo, customer_info, receiving_time, delivery_time, items_table,
      totals, payment_status, surcharge_discount, note, qr_tracking, order_no,
      footer_contact, custom_text. Khối HẸP (ghép nửa hàng): receiving_time,
      delivery_time, order_no, payment_status. Còn lại RỘNG (cả hàng).
    - 2 NHÓM: **động** (items_table/totals/qr/customer_info… tự điền từ đơn — chỉ
      bật/tắt + sắp xếp) và **text** (logo/note/footer_contact/custom_text — owner
      sửa `content`, có field vi+en nếu bilingual). Nhãn song ngữ cứng ở Bill.jsx.
    - `surcharge_discount` = khối nổi bật phụ thu/giảm (mặc định TẮT; `totals` đã
      gồm breakdown). `custom_text` = owner thêm nhiều bản (id `custom_<ts>`).
  - get_receipt: NULL → mặc định (bộ khối chuẩn, song ngữ bật). Cấu hình CŨ (5.3/
    5.4: shop_name/note_vi… KHÔNG có `blocks`) → **migrate-on-read** sang shape khối
    (giữ nội dung text owner đã nhập); lần PUT sau lưu shape mới. update_receipt GIỮ
    logo_url đang lưu (PUT không đổi được logo_url).
  - Endpoints: GET /settings/receipt (mọi role), PUT (owner), **POST
    /settings/receipt/logo (owner)** — Pillow validate + resize ≤480px + optimize →
    {upload_dir}/logo/{tenant_id}.png, trả logo_url cache-bust `?v=mtime`. nginx
    serve `/uploads/` (scripts/nginx-pos.conf). Deps: `pillow`, `python-multipart`.
  - Frontend: Bill.jsx render theo khối (gom enabled theo row, 1 khối=full / 2 khối=
    left+right, song ngữ). Màn cấu hình /settings/receipt (menu ☰, owner): builder
    kéo-thả + nút ↑/↓ sắp xếp, toggle bật/tắt, Ghép/Tách khối, ✎ sửa khối, + khối,
    toggle "Hiện tiếng Anh", preview 80mm realtime.
  - **Stage 5.7 — nâng cao: NHÃN sửa được + ĐỊNH DẠNG khối + divider/spacer + ghép
    TỰ DO.**
    - **Nhãn**: mọi nhãn cố định mỗi khối lưu ở `content` dạng `<key>_vi`/`<key>_en`
      (vd logo.title, items_table.svc/qty/price/total, totals.subtotal/total…).
      THIẾU → Bill fallback về text cứng mặc định (LDEF trong Bill.jsx + BLOCK_LABELS
      trong receipt.js — 2 nguồn mirror). Giá trị ĐỘNG (tên khách/tiền/mã đơn/QR)
      KHÔNG sửa, tự điền từ đơn.
    - **Định dạng/khối**: thêm field `bold` (bool), `align` (left|center|right; None
      → mặc định theo type), `size` (small|normal|large) — Bill áp qua class
      `rcp__al-*`/`rcp__sz-*`/`rcp__bold` (size large/small ép font con qua
      `font-size:inherit`). In nhiệt 80mm vẫn vừa.
    - **Khối mới**: `divider` (content.style dashed|solid) + `spacer` (content.height
      small|medium). Auto kẻ-mảnh-giữa-hàng BỎ QUA quanh divider/spacer để khỏi trùng.
    - **Ghép tự do**: bỏ ràng buộc "khối hẹp" — ghép 2 khối BẤT KỲ vào 1 hàng (kéo
      khối đơn thả vào ô "＋ghép" của khối đơn khác, HOẶC nút Ghép/Tách). Owner tự
      xem preview chịu trách nhiệm wrap.
    - Migrate: cấu hình 5.6 cũ (block thiếu bold/align/size/nhãn) → GET tự thêm
      default qua response_model (bold=false, size=normal, align=None) + Bill fallback
      nhãn; KHÔNG mất nội dung đã lưu.
  - **Stage 5.8 — dọn dẹp theo test thực tế:**
    - **Tách Tên/ĐT**: `customer_info` → 2 khối độc lập `customer_name` +
      `customer_phone` (tự sắp xếp/ghép/định dạng riêng). Migrate: customer_info cũ
      → 2 khối, GIỮ enabled + nhãn (name_*→label_*, tel_*→label_*).
    - **BỎ kẻ ngang tự động**: Bill KHÔNG tự chèn kẻ giữa khối nữa — kẻ CHỈ từ khối
      `divider` owner chèn (toàn quyền kiểm soát).
    - **Bold tách nhãn vs giá trị**: khối FIELD (customer_name/phone, receiving_time,
      delivery_time, order_no) dùng `bold_label` + `bold_value` (bool|None; None →
      fallback `bold` cũ) — render qua `rcp__lblbold .rcp__lbl` / `rcp__valbold
      .rcp__val`. Khối chỉ-text (logo/custom_text) giữ 1 cờ `bold`.
    - **BỎ khối text cố định trùng custom_text**: gỡ `note`, `footer_contact` (owner
      gõ lại vào "Văn bản tự do" — KHÔNG auto chuyển nội dung). GIỮ logo + khối động
      + divider/spacer/custom_text.
    - **Gộp phụ thu/giảm vào totals**: gỡ khối `surcharge_discount`. Dòng Tạm tính/
      Phụ thu/Giảm CHỈ hiện khi đơn thật sự có (surcharge_amount>0 || discount_amount
      >0); đơn thường → chỉ TỔNG CỘNG. Một nguồn duy nhất, tự ẩn/hiện theo dữ liệu.
    - Migrate-on-read (`_migrate_blocks`): tách customer_info, bỏ note/footer/
      surcharge_discount + khối lạ; gom theo row, chunk ≤2 khối/hàng, đánh lại
      row/col. GIỮ cấu hình owner còn lại.
    - **Logo CHỈ ẢNH**: khối `logo` bỏ tên tiệm + tiêu đề "BIÊN NHẬN" — chỉ render
      `logo_url`. Tên tiệm / tiêu đề là `custom_text` (dùng checkbox Title). Migrate:
      logo cũ có shop_name/title_* → TÁCH thành custom_text (giữ nội dung), logo
      content rỗng. (Stage 5.10: mẫu gốc dùng placeholder "[Tên tiệm]" thay tên thật.)
    - **Định dạng thêm**: `italic` (mọi khối text) + `title` (custom_text → cỡ lớn
      nhất `rcp__sz-title` + đậm + giữa, shortcut tiêu đề). Cỡ chữ tăng mỗi cấp +1
      (small 12 / normal 14 / large 18 / title 22 px) — vẫn vừa khổ 80mm.
    - **Trạng thái thanh toán**: 2 text owner sửa (`paid_*`/`unpaid_*`, vd "ĐÃ TRẢ"/
      "CÒN NỢ") — `paid` ↔ còn lại. Border ÔM VỪA chữ (inline-block), không full ngang.
    - **QR**: bỏ caption mặc định (muốn chữ → custom_text). **Link tracking per-tenant**
      `track_base_url` (top-level receipt_config, owner sửa); QR = `track_base_url` +
      order_code. Rỗng → mặc định `https://track.giatui2h.com/track/` (2H không gãy).
  - **Stage 5.9 — sửa bug + UX (chỉ frontend/CSS, KHÔNG đổi backend):**
    - **Bug cỡ chữ bảng món**: `.rcp__table` có `font-size:11px` cố định nên th/td
      không nhận cỡ khối → thêm `.rcp__fmt .rcp__table` vào danh sách `font-size:
      inherit`; `.rcp__th-en` đổi sang `0.7em` (co theo cỡ). Giờ items_table áp
      small/normal/large/title như mọi khối.
    - **Dòng tổng tiền**: BỎ lý do trong ngoặc (chỉ "Phụ thu"/"Giảm giá"); mọi dòng
      căn 2 đầu qua `.rcp__row-lbl` (flex:1) + `.rcp__row-amt` (nowrap, padding-left).
      Nhãn vẫn sửa được (mặc định discount = "Giảm giá").
    - **Tên khối custom_text trong builder** = nội dung rút gọn ~28 ký tự
      (`blockListLabel`); rỗng → "Văn bản tự do (trống)".
    - **Nút ⧉ nhân bản khối**: chèn bản sao ngay dưới (type+content+format), col=full,
      enabled=true — nhanh tạo nhiều custom_text/divider/spacer.
  - **Stage 5.10 — mẫu gốc nền tảng + mẫu mặc định per-tenant + fix xóa khối copy:**
    - **Fix bug xóa khối**: thêm field `removable` (bool) cho mỗi khối. Khối owner
      THÊM (custom_text/divider/spacer) và khối do **COPY** (mọi loại) → `removable=
      true` (hiện 🗑). Khối GỐC hệ thống → `removable=false` (chỉ tắt). Builder hiện
      🗑 theo `blk.removable` (KHÔNG theo type nữa). Migrate cấu hình cũ (chưa có
      `removable`): custom_text/divider/spacer → true, còn lại → false.
    - **Mẫu gốc nền tảng** (`DEFAULT_RECEIPT`/`_default_blocks`): giống bố cục/định
      dạng/nhãn bill 2H nhưng **PLACEHOLDER** — tên tiệm "[Tên tiệm]", chân phiếu
      "[Địa chỉ] · [Số điện thoại]", logo trống, track_base_url trống, ghi chú trách
      nhiệm mẫu. KHÔNG lộ thông tin 2H. Tenant MỚI dùng mẫu này (qua fallback
      get_receipt khi chưa có config). **2H giữ NGUYÊN config hiện tại** (không ghi đè).
    - **Mẫu mặc định per-tenant**: cột `tenant_settings.receipt_default_config` JSONB
      (migration d8e9f0a1b2c3). Endpoints (owner): POST /settings/receipt/save-default
      (lưu active làm mẫu mặc định), POST /settings/receipt/restore-default (active =
      mẫu mặc định tenant; CHƯA lưu → fallback mẫu gốc nền tảng), GET
      /settings/receipt/status → {has_tenant_default}. Frontend: 2 nút + xác nhận
      (restore "không hoàn tác") + 3 trạng thái (đang dùng / mẫu tenant đã lưu /
      fallback mẫu gốc). Tenant-scoped (mẫu tenant này không lẫn tenant khác).
  - **Stage 5.10.1 — fix bug xóa khối trong hàng ghép (chỉ frontend):** trước đây
    `removeBlock(ri)` splice CẢ HÀNG (xóa cả 2 khối left/right). Sửa: xóa theo (ri,ci)
    → đúng 1 khối; hàng còn 1 khối → `col='full'`; hàng rỗng → bỏ hàng. Tách pure
    helpers `blocksToRows`/`rowsToBlocks`/`removeCellFromRows` ra `lib/receipt.js`
    (dùng chung + test được). Mọi thao tác builder theo (ri,ci) — toggle/✎/⧉(id mới)/
    ⊟ — không nhầm sang khối cùng row.
  - **Stage 5.10.2 — bill hiện TÊN CHIẾN DỊCH phụ thu/giảm (chỉ frontend):** khối
    `totals` trên BILL IN THẬT dùng `order.surcharge_reason` / `order.discount_reason`
    làm nhãn dòng (vd "Phụ Thu Tết", "Giảm giá khai trương"); KHÔNG có reason →
    fallback nhãn chung sửa được ("Phụ thu"/"Giảm giá"). Subtotal/total giữ nhãn
    chung. Vẫn căn 2 đầu (rcp__row-lbl/amt). Preview builder dùng SAMPLE_ORDER KHÔNG
    có reason → giữ nhãn chung (không đổi).

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
- Endpoint công khai duy nhất: GET /public/track/{order_code} (Stage 5.2; gắn
  TRỰC TIẾP lên app, NGOÀI /api/v1) — không auth, rate limit theo IP (Redis,
  fixed-window, fail-open nếu Redis lỗi; IP lấy từ X-Real-IP do nginx ghi đè).
  Trả: order_code, order_status, pickup_at, timeline (order_tracking_logs:
  status+at), branch {name, address, phone}. KHÔNG lộ: tiền (total/paid/amount),
  payment_status, tên/SĐT KHÁCH, tenant_id/branch_id, notes. (SĐT/địa chỉ ở đây
  là LIÊN HỆ CHI NHÁNH — thông tin kinh doanh công khai, KHÁC SĐT khách.)
  Mã sai → 404 ORDER_NOT_FOUND. Frontend: trang tĩnh nhẹ `track-site/index.html`
  (vanilla, không build) serve ở subdomain track.giatui2h.com (nginx
  `scripts/nginx-track.conf` + certbot). QR trên bill trỏ về đây (Bill.jsx:
  VITE_TRACK_BASE_URL, mặc định https://track.giatui2h.com).
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

## TƯƠNG THÍCH CHROME 56 / MÁY POS SUNMI T1-G (Android 6) — MÔI TRƯỜNG TỐI THIỂU PHẢI HỖ TRỢ

Máy POS thật chạy **Chrome/WebView 56** trên Android 6 (UA `…T1-G…Chrome/56.0.2924.87`,
~1765 lượt trong nginx access.log). Đây là MỐC TỐI THIỂU bắt buộc cho mọi UI. Bài học đã
trả giá (stage 6.21–6.27 — sửa viền/khoảng cách thẻ Kanban /board):

1. **flex `gap` KHÔNG chạy** (cần Chrome 84+) → trên flex container dùng `margin` /
   `> * + * { margin-* }` thay cho `gap`. (Toàn app đã theo pattern `> * + *`; 6.21 vá 4 chỗ sót.)
2. **KHÔNG có CSS Grid** (Grid từ Chrome 57) → LUÔN để layout fallback **NGOÀI** `@supports
   (display: grid)`; nhánh grid đặt TRONG `@supports`. Chrome 56 chạy fallback, Chrome mới chạy grid.
3. **`border-radius` + `box-shadow` CÙNG LÚC trên phần tử LỚN (card)** → **BUG PAINT**: thẻ
   giữa/cuối cột mất/đứt viền khi repaint (cuộn/chồng lớp). **CẢ radius LẪN shadow đều dính**
   (đã test riêng từng cái). → Khối LỚN trên Chrome 56: **KHÔNG radius, KHÔNG shadow, KHÔNG
   `overflow:hidden`**. Chỉ thêm radius/shadow trong nhánh `@supports(display:grid)` (Chrome mới).
   → Nhãn NHỎ (badge tiền/giờ) có `border-radius` nhưng KHÔNG shadow thì OK — giữ được.
4. **`var()` OK** (Chrome 49+) → màu token (`--ns-*`, …) chạy tốt, KHÔNG phải nguồn lỗi viền.
5. **Xếp NGANG nhiều thẻ: KHÔNG dùng `flex-wrap`** (bug paint flex-line — chỉ item ĐẦU mỗi
   dòng vẽ đúng viền). Dùng **`float`** (an toàn nhất: `float:left` + `width:calc(50% - …)` +
   `:nth-child(2n){margin-left}` + `:nth-child(odd){clear:left}` + clearfix `::after`) hoặc block.
6. **Service worker `autoUpdate`**: mỗi lần deploy, máy POS GIỮ bản cũ tới khi xóa cache / SW
   activate. → Sau deploy quan trọng: XÓA CACHE trên máy POS. Xác minh đã nạp bản mới bằng cách
   so **hash file `index-*.css`** máy đang nạp với file trong `pos-pwa/dist/` (build deterministic).
7. **KHÔNG kiểm UI bằng headless Chromium mới** — nó render nhánh grid/CSS mới, KHÔNG tái hiện
   bug Chrome 56. Headless chỉ để verify LOGIC/cấu trúc CSS built; **máy POS thật là thước đo duy
   nhất** cho lỗi tương thích. (Headless "PASS" nhiều lần nhưng máy thật vẫn lỗi — 6.22→6.24.)

**QUY TẮC CHUNG:** mọi component MỚI chạy trên máy POS (card, popup, modal, form) phải:
tránh `radius`+`shadow` trên khối lớn, tránh flex `gap`, tránh `flex-wrap` để xếp ngang, để
layout fallback ngoài `@supports(grid)`. **Test trên máy POS thật trước khi coi là xong.**

## TEST

- Test bắt buộc cho MỌI logic liên quan tiền: cashflow formula (parametrized),
  shift reconciliation, sign convention, scenario integration (mở ca → đơn →
  thu → refund → đóng ca → kiểm tra expected/difference/aggregates).
- Viết test TRƯỚC khi viết service cho logic tài chính.
- **DATABASE TEST TÁCH RIÊNG — KHÔNG BAO GIỜ chạy test trên DB sản xuất.** Test
  TRUNCATE bảng giữa mỗi case nên PHẢI dùng DB riêng (`laundry_test`):
  - `tests/conftest.py` trỏ `DATABASE_URL` sang DB test TRƯỚC khi import app, tự
    tạo `laundry_test` nếu chưa có và `alembic upgrade head` lên đó (mỗi session).
  - Nguồn URL test: env `TEST_DATABASE_URL`; nếu không set thì tự suy ra bằng cách
    đổi tên db trong `DATABASE_URL` thành `<db>_test`.
  - LƯỚI AN TOÀN: conftest + fixture `clean_db` ASSERT tên DB kết thúc `_test`
    TRƯỚC mọi TRUNCATE; nếu không phải → raise, dừng ngay (chống xóa nhầm DB thật).
- Chạy test (set TEST_DATABASE_URL rõ ràng cho chắc chắn):
  ```
  docker compose exec \
    -e TEST_DATABASE_URL="postgresql+asyncpg://laundry:change_me_in_prod@postgres:5432/laundry_test" \
    app sh -c "cd /code && pytest tests/ -x -q"
  ```
  (Bỏ `-e ...` cũng được — conftest tự suy ra `laundry_test` từ `DATABASE_URL`.)
- alembic chạy được trên cả 2 DB: prod đọc `DATABASE_URL` mặc định; test set
  `DATABASE_URL`/`TEST_DATABASE_URL` trỏ `laundry_test` rồi `alembic upgrade head`.
- Sau mỗi thay đổi code, chạy test và báo kết quả trước khi kết thúc task.

## WORKFLOW

- Commit sau mỗi task hoàn chỉnh, message tiếng Anh ngắn gọn (feat:/fix:/test:).
- Khi user chốt một quyết định nghiệp vụ mới trong phiên làm việc,
  cập nhật ngay vào file CLAUDE.md này.
- Khi sửa file mà str_replace báo NOT FOUND: đọc lại nội dung file thực tế
  trước khi thử lại, không đoán.
- Secrets (DB password, JWT secret) chỉ nằm trong .env — file .env trong
  .gitignore, không bao giờ commit.
- Seed dữ liệu dev (idempotent):
  `docker compose exec app sh -c "cd /code && python -m scripts.seed"`

## QUYẾT ĐỊNH NGHIỆP VỤ ĐÃ CHỐT

- **Giao đơn còn nợ KHÔNG tạo field riêng — dùng `payment_status='debt'` (chốt
  Stage 3.7A).** PATCH status sang `delivered` mà đơn còn `unpaid`/`partial` →
  backend KHÔNG chặn, chỉ trả cờ `requires_payment=true` trong OrderOut để UI ép
  hỏi thanh toán. Backend không cấm vì ghi nợ là hợp lệ.
  - **Lý do:** "đơn giao-nợ có chủ đích" đã biểu diễn được bằng một dòng `debt`
    trong `payments` (làm `payment_status='debt'`) — KHÔNG cần thêm cột boolean
    `delivered_on_credit`. Quy trình UI: lúc giao, hoặc thu tiền, hoặc bấm "ghi
    nợ" (tạo payment type=debt). Đã ghi nợ → status='debt' → `requires_payment`
    KHÔNG bật nữa.
  - **Cách áp dụng:** `requires_payment` chỉ true khi `new_status=='delivered'`
    và `payment_status in (unpaid, partial)`. Cờ này transient (set trên ORM
    object trước khi serialize), KHÔNG lưu DB; các response khác mặc định false.

- **`payment_status` gộp hai loại "partial" làm một (chốt Stage 2c).** Cả
  "partial vì chưa thu đủ" và "partial vì đã hoàn một phần" đều trả về cùng
  `'partial'` — KHÔNG tách status riêng cho trường hợp có refund. Đã cân nhắc
  và chấp nhận gộp.
  - **Lý do:** sự phân biệt nằm ở payment history (đơn có dòng `refund` hay
    không), status không cần gánh thêm; refund hiếm trong nghiệp vụ Giặt Ủi 2H;
    báo cáo refund làm bằng report query lọc `transaction_type` + `reason`,
    không dựa vào `payment_status`.
  - **Cách áp dụng:** không thêm enum mới cho `payment_status`; muốn biết đơn
    có hoàn tiền hay không thì query `payments` theo `transaction_type IN
    ('refund','cancel_paid')`, đừng kỳ vọng đọc được từ status. Xem thứ tự ưu
    tiên status ở QUY TẮC TÀI CHÍNH #7.

- **Bảng giá động: model tier 2 bảng (chốt Stage 3.5A).** `services` +
  `service_tiers`, KHÔNG nhồi bậc giá vào JSON một cột. pricing_type `per_unit`
  (nhân theo lượng) vs `tier` (bậc cân). Bậc match = bậc đầu tiên (sort max_value
  tăng dần) có `quantity ≤ max_value`; không bậc nào khớp → dùng bậc overflow
  (`max_value=NULL`). `per_unit` trên TỪNG bậc phân biệt giá trọn gói vs tính
  theo đơn vị, nên ">7kg=18k/kg" chỉ là một bậc overflow `per_unit=true` —
  không cần cột đặc biệt.
  - **Cách áp dụng:** dòng đơn gửi `service_id` + `quantity` thì server tự tra
    giá + snapshot (`app/services/pricing.py::price_line`); KHÔNG có service_id
    thì BẮT BUỘC `service_name` + `unit_price` (nhập tay, giữ tương thích cũ).
    snapshot tên bậc tier vào `service_name` dạng "Giặt sấy (≤3kg)".

- **Sổ quỹ thu-chi: chỉ phần TIỀN MẶT vào reconciliation; `total_income`/
  `total_expense` là cash-only (chốt Stage 4.2).** `cash_transactions` cho phép
  payment_method cash/transfer/qr, nhưng CHỈ thu/chi tiền mặt ảnh hưởng KÉT nên
  chỉ phần cash được cộng/trừ vào `closing_cash_expected` và lưu vào hai cột
  aggregate. Thu/chi qua transfer/qr vẫn ghi nhận (để báo cáo dòng tiền) nhưng
  KHÔNG vào két, KHÔNG vào `total_income`/`total_expense`.
  - **Lý do:** giữ bất biến reconciliation minh bạch, tự kiểm:
    `expected = opening + total_cash(payments) + total_income − total_expense`
    đúng KHÍT với các cột đã lưu. Tách biệt "ảnh hưởng két" (cash) khỏi "ghi nhận
    dòng tiền" (mọi method) — đúng mục tiêu #1 chống thất thoát TIỀN MẶT.
  - **Cách áp dụng:** muốn tổng thu/chi MỌI method thì query `cash_transactions`
    theo `type` (đừng đọc từ `shifts.total_income`); hai cột trên chỉ là cash.
    `amount` luôn dương (magnitude), dấu suy từ `type`; sửa sai = ghi giao dịch
    đối ứng (bảng IMMUTABLE như payments, trigger chặn UPDATE/DELETE).

- **Danh mục là thực thể riêng; xóa danh mục = CHẶN nếu còn dịch vụ (không tự
  null hóa) (chốt Stage 4.3).** `services.category` text → `categories` (icon +
  display_order) + `services.category_id`. Chọn danh mục cho dịch vụ bằng DROPDOWN
  từ danh sách chuẩn — KHÔNG gõ text tự do (tránh trùng/sai chính tả phân mảnh tab).
  - **Lý do:** danh mục cần icon + thứ tự + sửa-một-chỗ-đổi-mọi-nơi; text tự do
    không làm được. Chặn xóa (thay vì set category_id=null hàng loạt) là cách AN
    TOÀN: tránh mất phân loại ngầm; báo "còn N dịch vụ" để owner chủ động xử lý.
  - **Cách áp dụng:** ServiceCreate/Update nhận `category_id` (validate thuộc tenant
    + active → 422 INVALID_CATEGORY); ServiceOut trả `category_id` + object `category`.
    Xóa danh mục: `soft_delete_category` đếm service ACTIVE cùng category_id, >0 →
    409 CATEGORY_IN_USE. Migration backfill: gom các text `category` DISTINCT theo
    (tenant, name) thành 1 category, map category_id, rồi DROP cột text (đã verify
    trên prod thật: "Giặt sấy"×4 + "Giặt hấp"×1 → 2 category, 0 mất mát).

- **Phiếu bill: layout SONG NGỮ CỐ ĐỊNH thay vì blocks reorder; logo lưu file
  tĩnh; phụ thu là display-only (chốt Stage 5.3).** Bỏ hệ thống `blocks`
  {key,enabled,order} (Stage 4.1) — layout giờ khớp cứng mẫu giấy 2H, nhãn song
  ngữ Việt/Anh hardcode trong Bill.jsx. Owner chỉ sửa NỘI DUNG (text + logo ảnh)
  và bật/tắt 2 khối: ghi chú trách nhiệm + phụ thu.
  - **Lý do:** mẫu 2H là phiếu giấy quy chuẩn, không cần khách tự xếp lại khối;
    cố định layout giảm phức tạp và bảo đảm in đúng mẫu. Logo lưu file tĩnh
    (nginx serve /uploads/) thay vì base64 trong DB để phiếu nhẹ + cache được.
  - **Cách áp dụng:** logo_url chỉ đổi qua POST /settings/receipt/logo (Pillow
    validate type/size + resize ≤480px + optimize PNG; cache-bust `?v=mtime`);
    PUT /settings/receipt KHÔNG nhận logo_url (ReceiptUpdate strip về "", service
    giữ giá trị cũ). Bill không còn hiển thị trạng thái thanh toán/đã thu/còn lại
    như mẫu cũ — mẫu 2H tập trung tổng đơn cho khách.
  - **CẬP NHẬT Stage 5.4:** phụ thu display-only đã GỠ khỏi receipt_config. Phụ
    thu/giảm giờ là TIỀN THẬT theo từng đơn (xem quyết định 5.4 dưới).
  - **ĐẢO HƯỚNG Stage 5.6:** BỎ layout cứng 2H. Quay lại hệ KHỐI linh hoạt (owner
    tự thêm/bớt/sắp xếp/ghép 2 khối/hàng/bật-tắt tiếng Anh) nhưng GIÀU hơn bản
    Stage 4.1: mỗi khối có row/col + content riêng + nhãn song ngữ cứng. Lý do:
    chủ chuỗi cần tùy biến bố cục phiếu theo từng tiệm, không khóa cứng 1 mẫu. Cấu
    hình 5.3/5.4 cũ được migrate-on-read sang shape khối (không mất nội dung).

- **Phụ thu & giảm giá vào TIỀN THẬT, snapshot theo đơn; rule tự áp làm mặc định,
  nhân viên ghi đè được (chốt Stage 5.4).** `total_amount = subtotal +
  surcharge_amount − discount_amount`, total_amount là tiền thật (vào payment,
  doanh thu, đối soát ca). price_rules tự áp theo NGÀY VN; nhập tay khi tạo đơn
  GHI ĐÈ rule (không cộng dồn).
  - **Lý do:** phụ thu Tết / giảm khách quen phải phản ánh đúng số tiền thu thật
    (khác hẳn display-only của 5.3). Snapshot lúc tạo (bất biến như giá món) để
    đổi/xóa rule KHÔNG ảnh hưởng đơn cũ. Reconciliation tự đúng vì payment thu
    theo total thật — KHÔNG cần sửa shift_service (đã verify bằng test).
  - **Cách áp dụng:** POST /orders nhận `surcharge`/`discount`
    {value_type: percent|fixed, value, reason}. percent tính trên `subtotal`
    (tổng món gốc). discount bị CLAMP ≤ subtotal+surcharge (total không âm). POS
    LUÔN gửi giá trị đang hiển thị (đã gồm rule điền sẵn + sửa tay) → backend dùng
    đúng số đó, KHÔNG tự áp lại; client khác không gửi gì thì backend tự áp rule
    (fallback). Mỗi đơn có discount>0 ghi `discount_logs` (ai/đơn/số tiền/lý do)
    cho GET /reports/discounts. Ví dụ: subtotal 200k + phụ thu 10% (20k) − giảm
    cố định 15k = total 205k.

## NỢ KỸ THUẬT ĐÃ BIẾT

- **Múi giờ POS cố định Việt Nam (UTC+7) ở frontend (chốt Stage 3.8).** Trước đây
  picker giờ giao dùng giờ LOCAL trình duyệt → máy POS để UTC làm giờ chọn lệch 7h
  thành quá khứ → 422. Nay `pos-pwa/src/lib/datetime.js` thao tác trên "VN wall
  Date" (Date có trường UTC mã hoá giờ VN), gửi backend bằng `vnWallToISO` (trừ 7h
  → ISO UTC). Mọi hiển thị pickup_at (board/phiếu/chi tiết) cũng quy về VN qua
  `formatPickupShort`. Đã verify độc lập với TZ máy (UTC/VN/New York cho kết quả
  như nhau): 16:30 VN → "09:30Z". LƯU Ý: `formatDateTime` (created_at...) VẪN dùng
  local — nếu cần hiển thị các mốc khác theo VN thì quy đổi tương tự.
- **API serialize Decimal số tròn lớn ra notation khoa học** (vd `"5E+4"` thay
  vì `"50000"`). Giá trị NUMERIC trong DB vẫn ĐÚNG — chỉ là cách Pydantic/JSON
  hóa Decimal. Hệ quả:
  - Frontend (Stage 3) PHẢI parse field tiền bằng `Number()` / `parseFloat()`
    trước khi format VND; KHÔNG hiển thị raw string (sẽ ra "5E+4").
  - Test backend đã phòng bằng helper `_num(x) = int(Decimal(str(x)))` nên không
    vỡ, nhưng đây là bẫy cho client.
  - **Cân nhắc fix gốc:** thêm Pydantic field serializer chuẩn hóa Decimal→số
    nguyên cho mọi field tiền (amount, total_amount, opening_cash, các total_*,
    closing_cash_*, cash_difference...) để API luôn trả số nguyên thường. Làm
    một lần ở base schema/annotated type dùng chung.
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
  `order_code` PHẢI dùng đúng tên này. LƯU Ý (Stage 5.1): sequence keyed theo
  `code` (bất biến), KHÔNG theo `order_prefix` — đổi prefix KHÔNG đụng sequence.
- **`order_prefix` mặc định = `code` có thể đụng prefix tùy biến của branch khác
  (Stage 5.1).** Nếu owner đã đặt prefix tùy biến của branch cũ TRÙNG với `code`
  sẽ-sinh của branch mới (vd đặt prefix "B4" rồi tạo branch thứ 4 → code "B4"),
  `create_branch` chặn sớm với 409 PREFIX_TAKEN (thay vì 500 từ unique index) —
  owner đổi prefix branch cũ trước. Hiếm (owner ít đặt prefix dạng "B"+số).
- **Tracking công khai tra theo order_code KHÔNG unique toàn cục (Stage 5.2).**
  `order_code` chỉ unique trong 1 tenant (uq (tenant_id, order_code)); 2 tenant có
  thể trùng mã (vd cùng prefix + số). `get_public_tracking` lấy bản MỚI NHẤT theo
  created_at. MVP 1 tenant nên đủ định danh. TRƯỚC KHI onboard tenant #2: thêm
  tenant context vào URL tracking (subdomain/slug per tenant, hoặc mã đơn nhúng
  tenant) — cùng nhóm việc với "login phone-only chưa có tenant context".

- [x] Stage 1: skeleton + migration baseline + auth (login/refresh/logout/me) + CRUD tenants/branches/users
- [x] Stage 2: shifts (open/close + reconciliation) + orders + payments + Telegram alert đóng ca
- [x] Stage 3: POS PWA (login, mở/đóng ca, tạo đơn, thu tiền, đổi trạng thái)
- [x] Stage 3.5A: bảng giá dịch vụ động (services + service_tiers) + CRUD + snapshot giá vào order_items
- [x] Stage 3.7A (backend): orders.pickup_at (giờ hẹn giao) + GET /orders/board (dashboard vận hành) + cờ requires_payment khi giao đơn còn nợ
- [x] Stage 3.7B (frontend): wheel time picker + tab Bảng đơn (Kanban) + luồng giao-thanh-toán (modal requires_payment)
- [x] Stage 3.8: thiết kế lại màn tạo đơn 3 vùng không cuộn + tab danh mục/Hay chọn + fix pickup_at múi giờ VN + tenant_settings.default_turnaround_hours + GET/PUT /settings
- [x] Stage 3.9: cho lùi trạng thái có kiểm soát + gộp màn "Đơn hàng" (Kanban/List + search q) + nav restructure (☰ menu)
- [x] Stage 4.1: custom bill template (receipt_config) + GET/PUT /settings/receipt + màn cấu hình phiếu (preview 80mm realtime)
- [x] Stage 4.2: sổ quỹ thu-chi (cash_transactions IMMUTABLE) + tích hợp đóng ca (expected cộng thu/trừ chi tiền mặt) + màn "Sổ quỹ" POS + Telegram kèm dòng thu/chi
- [x] Stage 4.3: danh mục dịch vụ thành thực thể riêng (categories: icon + thứ tự) + services.category_id + migration backfill (gom text trùng) + CRUD + màn "Danh mục" (icon picker, ↑/↓) + dropdown chọn danh mục ở bảng giá + tab danh mục icon riêng ở màn tạo đơn
- [x] Stage 5.1: order_code prefix tùy biến per-branch (branches.order_prefix) + format `{prefix}-{số ≥5 chữ số, tự nới}` + CRUD validate (định dạng + unique trong tenant) + màn "Chi nhánh" (owner sửa tiền tố)
- [ ] Stage 4: pilot 1 branch Giặt Ủi 2H (chạy song song sổ tay 2 tuần)
- [x] Stage 5.2: trang tracking công khai track.giatui2h.com — GET /public/track/{order_code} (read-only, rate-limit IP/Redis, KHÔNG lộ tiền/khách) + trang tĩnh nhẹ (step indicator Đã nhận→…→Đã giao, liên hệ branch) + nginx subdomain + certbot SSL + QR bill trỏ về subdomain
- [x] Stage 5.3: phiếu bill SONG NGỮ Việt/Anh khớp mẫu 2H (logo ảnh + bảng món Service/Qty/Price/Total + ghi chú trách nhiệm + footer hotline/web/zalo + phụ thu Tết bật/tắt) — POST /settings/receipt/logo (Pillow resize/optimize) + nginx serve /uploads/ + order customer_phone + màn cấu hình upload logo & sửa text song ngữ & preview realtime
- [x] Stage 5.4: phụ thu & giảm giá vào TIỀN THẬT — price_rules (tự áp theo ngày, owner CRUD) + orders.subtotal/surcharge_amount/discount_amount (snapshot, total=subtotal+surcharge−discount) + POST /orders nhận surcharge/discount (nhập tay ghi đè rule) + discount_logs + GET /reports/discounts (theo nhân viên/ngày) + màn xác nhận đơn (badge "tự áp" + breakdown Tạm tính→+Phụ thu→−Giảm→Tổng cộng) + màn quản lý quy tắc + bill hiện phụ thu/giảm. (Bỏ phụ thu display-only của 5.3.)
- [x] Stage 5.10.2: bill IN THẬT hiện TÊN CHIẾN DỊCH phụ thu/giảm (surcharge_reason/discount_reason) thay nhãn chung; không reason → fallback "Phụ thu"/"Giảm giá"; căn 2 đầu; preview builder giữ nhãn chung. Chỉ frontend.
- [x] Stage 5.10.1: fix bug xóa khối trong hàng ghép — xóa theo (ri,ci) đúng 1 khối (trước đây splice cả hàng → mất cả 2); khối còn lại về col=full; tách pure helpers ra lib + test. Chỉ frontend.
- [x] Stage 5.10: mẫu gốc nền tảng (placeholder, cho tenant mới) + mẫu mặc định per-tenant (receipt_default_config + Lưu/Khôi phục + 3 trạng thái) + fix bug xóa khối copy (field `removable`: khối copy/owner xóa được, khối gốc chỉ tắt). 2H giữ nguyên config. Migration d8e9f0a1b2c3.
- [x] Stage 5.9: bill builder sửa bug + UX — fix cỡ chữ bảng món (table nhận size); dòng tổng tiền bỏ ngoặc lý do + căn 2 đầu (nhãn trái/số phải); khối custom_text hiện nội dung rút gọn trong builder; nút ⧉ nhân bản khối (giữ nội dung+định dạng). Chỉ frontend/CSS.
- [x] Stage 5.8: bill builder dọn dẹp + tùy biến sâu — tách Tên/ĐT 2 khối; logo CHỈ ẢNH (tên tiệm/tiêu đề → custom_text, migrate giữ nội dung); bỏ kẻ ngang tự động; bold tách nhãn/giá trị + italic + checkbox Title (custom_text) + tăng cỡ chữ mỗi cấp +1; bỏ note/footer_contact; gộp Tạm tính/Phụ thu/Giảm vào totals (chỉ hiện khi đơn có); trạng thái TT 2 text sửa được + border ôm chữ; QR bỏ caption + link tracking per-tenant (track_base_url); migrate-on-read giữ cấu hình owner
- [x] Stage 5.7: bill builder nâng cao — sửa MỌI nhãn text (song ngữ, lưu content `<key>_vi/_en`, giá trị động giữ nguyên) + định dạng theo khối (bold/align/size) + khối divider (dashed/solid) & spacer (small/medium) + ghép TỰ DO 2 khối bất kỳ/hàng (kéo-thả + nút) + popup sửa khối (nhãn+nội dung+định dạng) + migrate cấu hình 5.6 giữ nguyên
- [x] Stage 5.6: bill builder THEO KHỐI (thay layout cứng 2H của 5.3) — receipt_config {bilingual, logo_url, blocks[{id,type,enabled,row,col,content}]} + migrate-on-read cấu hình cũ + Bill.jsx render theo khối (2 khối/hàng, song ngữ) + màn builder (kéo-thả + nút sắp xếp, bật/tắt, ghép/tách khối hẹp, sửa nội dung text, thêm văn bản tự do, toggle tiếng Anh, preview 80mm realtime)
- [x] Stage 5.5: màn quản lý tài khoản nhân viên (phân quyền theo role + branch) — bổ sung POST /users/{id}/reset-password + PATCH /users/{id}/status (suspended/active, không tự khóa) + list kèm branch_name/in_open_shift + màn "Nhân viên" (owner+manager, ☰): danh sách badge role/trạng thái/đang-trong-ca, lọc theo CN, thêm/sửa/đặt-lại-MK/khóa-mở, hỗ trợ tài khoản theo ca (username). KHÔNG thêm role mới.
- [x] Stage 6.55 (TÀI CHÍNH — VÁ lỗ hổng mở ca không đối chiếu tiền đầu ca; Mức 2 = cho sửa, lệch BẮT lý do; test-first; CÓ migration; ⚠️ CẦN MIGRATION + RESTART). **Lỗ hổng:** open_shift nhận opening_cash bất kỳ, KHÔNG so với cash_left_for_next ca trước → chênh đầu ca thất thoát không dấu vết. **MIGRATION `d4f5a6b7c8e9`** (← c3e4f5a6b7d8): `shifts.opening_diff` (Numeric(14,0) nullable) + `opening_diff_reason` (Text nullable) — additive. **MODEL** Shift +opening_diff +opening_diff_reason. **SERVICE `open_shift`** (+param opening_diff_reason): lấy ca ĐÓNG gần nhất cùng branch; `last is None` (ca ĐẦU) → MIỄN đối chiếu; có ca trước → `diff = opening_cash − cash_left_for_next`, `diff≠0` + thiếu lý do → **422 OPENING_DIFF_REASON_REQUIRED** (đai an toàn BACKEND, nhất quán cash_diff_reason); có lý do → lưu opening_diff (âm=thiếu/dương=thừa) + reason; khớp → NULL. **SCHEMA** ShiftOpen +opening_diff_reason (max 500); ShiftOut +opening_diff +opening_diff_reason; **OpeningSuggestion +has_previous** (FE biết khi nào đối chiếu — ca đầu=False). **API** open truyền reason; `GET /opening-suggestion` dùng `latest_closed_shift` trả thêm has_previous. **FE (CẢ 2 chỗ mở ca — không lách được):** Shift.jsx (form mở ca) + OrderNew.jsx (form mở ca inline 6.54): khi `has_previous && opening !== suggestion` → hiện `.shift__warn` (⚠️ lệch X so với để lại Y, amber radius 4 không shadow) + ô "Lý do lệch" bắt buộc; thiếu → lỗi DƯỚI ô (`.field-note--err`, không top); 422 → cũng hiện dưới ô; ca đầu (has_previous=False) → nhập tự do. **TEST (first):** khớp→opening_diff NULL; lệch thiếu lý do→422 (ca không mở nửa vời); lệch+lý do→opening_diff đúng dấu (−20k/+40k); ca đầu→miễn. Sửa `test_can_reopen_branch_after_close` (mở lại khớp 100000). Full suite **261 passed**. **REPORTS (owner_summary hiện opening_diff): HOÃN** — không tìm thấy CashDiffRow/owner_summary ở chỗ hiển nhiên; data đã expose qua ShiftOut → làm sau nếu cần. Build modern+legacy. CSS `index-DCfoQhBf.css`, JS `index-eo5zXmCH.js` (legacy `index-legacy-B3-rlPb6.js`). **⚠️ DEPLOY off-peak: `alembic upgrade head` (gồm d4f5a6b7c8e9 + 3 migration cũ a1c2e3f4d5b6/b2d3e4f5a6c7/c3e4f5a6b7d8 nếu prod chưa chạy — KIỂM `alembic current`) → `docker compose restart app`.** Migration FIRST, restart AFTER; KHÔNG restart khi test đang chạy.
- [x] Stage 6.54 (2 cải tiến luồng; frontend thuần, 2 commit). **KHẢO SÁT:** mở ca = `POST /shifts/open {opening_cash, branch_id?}` — CẦN tiền đầu ca (gợi ý `GET /shifts/opening-suggestion`), không 1-click thuần. Layout KHÔNG có context ca (chỉ Auth/Branch/TopbarSlot). board3__main & board3__actions (← → ☰) là ANH EM (không lồng) → bấm nút con không lan tới thân thẻ. **(1a) Mở ca tại màn Tạo đơn** (OrderNew, dùng API có sẵn — KHÔNG backend): màn `shiftState==='none'` thay nút "Về màn ca" bằng **form mở ca inline**: effect lấy gợi ý đầu ca điền sẵn MoneyInput `opening` + nút **"MỞ CA"** (`openShiftHere` → POST /shifts/open {opening_cash, branch_id nếu owner} → `checkShift()` → 'open' → vào thẳng tạo đơn) + nút phụ "Tới màn Ca". GIỮ bước nhập tiền đầu ca (không bỏ). `.on-open` (inline-block max-width 320, margin KHÔNG gap). **(1b) Nhãn tab "Ca" động → BỎ QUA (báo):** Layout không có state ca; làm động cần ShiftContext (wire qua Shift/OrderNew) hoặc polling (stale/nặng) = phức tạp → giữ "Ca" như cũ (user cho phép skip). **(2) Bấm THÂN thẻ Kanban → mở popup ☰** thay vì /orders/:id: `board3__main` onClick `goDetail`→`openSheet(o)` (+ onKeyDown Enter). ← → ☰ là anh em nên KHÔNG cần thêm stopPropagation (note button đã có); vào chi tiết qua nút "Chi tiết" trong popup. Build modern+legacy. CSS `index-DtvPMbku.css`, JS `index-DL7ghIvO.js` (legacy `index-legacy-Cyclpbq-.js`). Frontend-only, không restart, không test suite (API mở ca đã có sẵn).
- [x] Stage 6.53 (Tạo đơn — lối THOÁT/HỦY giữa chừng; frontend thuần). **(1)** Modal "Xác nhận đơn" thêm nút **"Hủy"** (`.cfm__cancel`, chữ đỏ `--danger` nhẹ, góc trên cạnh tiêu đề — tách xa nút "Tạo đơn" ở đáy tránh bấm nhầm; hiện ở CẢ bước 1+2 vì nằm trong `cfm__head`). `cancelDraft`: nếu đã nhập gì (`cart.length>0 || phone/custName/note`) → `window.confirm('Hủy đơn đang tạo? Thông tin chưa lưu sẽ mất.')` → đồng ý mới `navigate('/board')`; chưa nhập gì → thoát luôn. **KHÔNG gọi API** (đơn chưa vào DB trước nút "Tạo đơn" cuối — chỉ POST /orders ở `submit`; unmount xóa state nháp). **(2) BỎ QUA** lối thoát ở màn chọn dịch vụ: màn đó modal đóng → **tab Layout (Đơn hàng/Lịch sử/…) vẫn bấm được** để thoát; modal mới là chỗ kẹt (overlay che nav) nên chỉ cần nút Hủy ở modal. Build modern+legacy. CSS `index-BQQ3aPBw.css`, JS `index-C7OY-1fm.js` (legacy `index-legacy-CYgO1FRv.js`). Frontend-only, không restart, không test suite, không API.
- [x] Stage 6.52 (Chi tiết đơn — nút điều hướng header; frontend thuần, CSS+JSX). (1) THÊM nút **"Lịch sử"** (→ `/history`) vào cụm góc phải, thứ tự Tạo đơn · Lịch sử · Đơn hàng. (2) `.od__nav` to hơn: font 13→**14**, padding 6×12→**10×18** (dễ bấm POS). Build modern+legacy. CSS `index-BjKjhFs1.css`, JS `index-UK-kS5Pe.js` (legacy `index-legacy-DNlfHr0E.js`). Frontend-only, không restart, không test suite.
- [x] Stage 6.51 (THIẾT KẾ LẠI trang Chi tiết đơn `/orders/:id`; frontend thuần, KHÔNG backend/restart). **KHẢO SÁT:** GET /orders/:id = OrderDetailOut nên `order.tracking` ĐÃ về sẵn (6.41) — chỉ chưa render; items có service_name/quantity/subtotal + order có subtotal/surcharge/discount/total; paidSum=Σpayments, remaining=total−paidSum; lịch sử = GET /payments. **A6: pay-first popup ở OrderDetail chỉ kích hoạt qua `advance()` (nút "Chuyển sang"); KHÔNG đường giao hàng nào khác** → bỏ nút chuyển trạng thái ⇒ GỠ AN TOÀN advance + deliverModal + helper (payFullDeliver/payDebtDeliver/finishDeliverDetail/openDeliverPopup) + state (deliverModal/payMethod/debtMode/debtReason/payBusy); **pay-first vẫn nguyên ở Board/sheet**. **LÀM (rewrite OrderDetail.jsx + CSS `.od__*`):** HEADER mã (20/500) + badge "Đã thu"xanh/"Chưa thu"đỏ + badge trạng thái (`.hbadge--*`) + góc phải nút "Tạo đơn"(/orders/new)·"Đơn hàng"(/board). **2 CỘT** flex-wrap (≥720px 2 cột margin-left, <720px 1 cột margin-top — media query, KHÔNG gap): TRÁI = card "Thông tin" (Khách/SĐT/Hẹn lấy/Tạo lúc — BỎ chi nhánh vì OrderOut không có branch_name + ghi chú nền vàng/`.hexp__note`) + card "Hạng mục" (món + ×SL + thành tiền; phụ thu/giảm dòng riêng; Tổng đậm border-top); PHẢI = 2 metric card nền xám "Đã thu"(xanh)/"Còn lại"(đỏ nếu>0) + card "Tiến trình" (timeline `buildTimeline` tái dùng `.htl*`, KHÔNG nhãn thu) + card "Lịch sử thu/chi" (loại+PT+người+giờ+lý do+tiền; hoàn=đỏ/âm). **DÒNG HÀNH ĐỘNG** border-top: trái In lại bill (`window.print`) + Thu tiền (nếu chưa paid→/pay); phải Hoàn tiền (xanh `--success`, form 2 bước GIỮ NGUYÊN → POST /payments/refund) + Hủy đơn (đỏ, CancelOrderModal khi CANCELLABLE). **BỎ HẾT emoji** (🖨️➡️↩️💵🏦📝✓＋). Card radius 12 + border KHÔNG shadow; metric radius 8; badge radius 4; spacing margin. Token mới (var(--line)/--orange/--success/--danger/--muted). Giữ lớp cũ `.card/.kv/.detail*/.pay-row` (màn khác như OrderPay vẫn dùng). Verify đọc CSS build (KHÔNG headless). Build modern+legacy. CSS `index-CpRiD2N_.css`, JS `index-YV0QFhx0.js` (legacy `index-legacy-C8g-fsEZ.js`). Frontend-only, không restart, không test suite (không đụng backend).
- [x] Stage 6.50 (Tạo đơn — tự động GHI ĐÈ tên khách khi SĐT đã có customer; Cách 1, test-first; ⚠️ CẦN RESTART). **KHẢO SÁT (đã báo):** `order.customer_name` là `@property` JOIN `self.customer.full_name` ([order.py:52-54](app/models/order.py)) — Order KHÔNG snapshot tên → đổi `customers.full_name` đổi tên CẢ đơn cũ+mới (A2=(a), đã chấp nhận: quản lý bằng SĐT+mã đơn). Không có endpoint update customer trước đó. **LÀM qua `create_order` (atomic, KHÔNG endpoint riêng, KHÔNG migration):** OrderCreate thêm `customer_name: str | None = None` (max 255); khi `customer_id` đã có + `customer_name is not None` (KỂ CẢ "") → load Customer, nếu `full_name != customer_name.strip()` thì set (cùng transaction tạo đơn). `None` = không đụng (caller khác / đơn không sửa tên). Tên rỗng → full_name="" (KHÔNG giữ tên cũ; lý do: SĐT có thể bị thu hồi/đổi chủ — full_name nullable=False nên dùng "" chứ không NULL). **FE OrderNew submit:** nhánh `custFound` (link customer đã có) → `overwriteName = custName.trim()` → `body.customer_name = overwriteName` ("" = ghi đè rỗng); nhánh tạo customer mới KHÔNG gửi (giữ logic quick-create phone→tên). **TEST** `test_create_order_overwrites_customer_name`: "abc"+nhập"xyz"→"xyz" & đơn cũ JOIN cũng "xyz"; nhập ""→""; nhập trùng "abc"→giữ "abc". Full suite **257 passed**. Build modern+legacy. CSS `index-y12LDcX6.css` (KHÔNG đổi), JS `index-DU8xDN_f.js` (legacy `index-legacy-BgMZKXmu.js`). **⚠️ CẦN `docker compose restart app`** (BE đổi schema/service, KHÔNG migration). TRƯỚC restart: FE gửi `customer_name` nhưng BE cũ BỎ QUA field lạ (Pydantic ignore extra mặc định) → tên KHÔNG ghi đè (không lỗi). Sau restart → ghi đè hoạt động.
- [x] Stage 6.49 (Tạo đơn — autocomplete SĐT + hẹn giờ +3h + màn "đã tạo" 2 hàng nút). **KHẢO SÁT:** có model `Customer` (bảng customers: full_name, phone, email, notes — **tenant-scoped, KHÔNG branch_id**, xem [customer.py](app/models/customer.py)); `GET /customers` cũ CHỈ khớp SĐT chính xác (`phone==`). → branch-limit KHÔNG khả thi (customer không gắn branch) → search theo tenant (đúng MVP 1 tenant). **(1) AUTOCOMPLETE KHÁCH** — BE (đọc thuần, KHÔNG migration): `list_customers` thêm `q` → `or_(phone.ilike, full_name.ilike)` khớp MỘT PHẦN; API `GET /customers` thêm query `q`. Test `test_search_q_partial_phone_or_name`. FE OrderNew: effect debounce 400ms đổi `?phone=` → `?q=&limit=8` → state `custSug`+`sugOpen`; dropdown `.cust-ac__list` dưới ô SĐT (absolute, **border 1px KHÔNG box-shadow** — bug paint Chrome 56, radius 6, overflow cuộn, mỗi mục 40px "Tên · SĐT"); bấm `pickCust` điền SĐT+tên+link khách quen; khớp SĐT chính xác vẫn set custFound (hint "✓ Khách quen" + customer_id như cũ); gõ tiếp → ẩn (sugOpen). **(2) HẸN GIỜ mặc định = now + 3h** (`defaultPickupVnWall(3)`, làm tròn 15' giờ VN) thay 08:00 cũ (sửa cả initial state + reset openConfirm). **(3) MÀN "ĐÃ TẠO ĐƠN" 4 nút → 2 HÀNG** (`.ordok__actrow` flex, 2 nút flex:1, margin KHÔNG gap): hàng 1 "In lại bill"(printBillAndLabel)·"In liên 2"(Lien2PrintButton); hàng 2 "Tạo đơn mới"(startNew)·**"Đơn hàng"** (THÊM MỚI → `navigate('/board')`); bỏ emoji ＋. GIỮ logic tạo đơn/in/thanh toán. Full suite **256 passed**. Build modern+legacy. CSS `index-y12LDcX6.css`, JS `index-ZLWMYbtK.js` (legacy `index-legacy-Cd5uasei.js`). **⚠️ CẦN `docker compose restart app`** để kích hoạt param `q` (BE đổi, KHÔNG migration). TRƯỚC restart: FE gửi `?q=` nhưng BE cũ BỎ QUA (FastAPI không 422) → autocomplete KHÔNG ra gợi ý (không lỗi); việc 2,3 chạy ngay (frontend). Sau restart → autocomplete hoạt động.
- [x] Stage 6.48 (tab Lịch sử — toggle CHỌN sort; frontend thuần, backend param sort đã có từ 6.47). Ở dòng đếm "X đơn" thêm bên PHẢI cụm toggle: nhãn "Sắp xếp:" + 2 nút nhỏ (font 12, padding 5×10, radius 4) "Mới cập nhật" (`sort=updated_at`) | "Mới tạo" (`sort=created_at`); nút chọn nền cam (class `chip--active`), nút kia viền nhạt. State `sortKey` (mặc định **updated_at** — giữ hành vi 6.47) đưa vào `buildParams` (`p.set('sort', sortKey)`) + deps → bấm đổi sort → `load()` gọi lại GET /orders. `.history__count` thành flex space-between (count trái / toggle phải). **CHROME 56**: nút cách nhau margin (KHÔNG gap), radius 4, border 1px, không shadow; **compound `.history__sortbtn.chip--active`** (specificity 0,2,0) để nền cam THẮNG nền base `.history__sortbtn` (định nghĩa sau `.chip--active` global). GIỮ hàng lọc (tìm + 2 dropdown) + mọi logic lọc/tìm/tải-thêm/mở-rộng. Build modern+legacy. CSS `index-C5fnFBz9.css`, JS `index-BNY8eBSt.js` (legacy `index-legacy-CIxz9rZw.js`). Frontend-only, không restart, không test suite.
- [x] Stage 6.47 (2 sửa nhỏ; #1 frontend + #2 backend sort — ⚠️ CẦN RESTART). (1) **Sheet ☰** nút "Hủy" → **"Hủy đơn"** (tránh nhầm với "Đóng"); chỉ text, giữ logic (CANCELLABLE → CancelOrderModal). (2) **Sort tab Lịch sử theo updated_at (Cách A đã duyệt)** — KHÔNG migration (updated_at có sẵn UpdatedAtMixin): **BE** `list_orders` thêm param `sort: str = "created_at"`; `sort=="updated_at"` → `order_by(Order.updated_at.desc())`, mặc định created_at (giữ hành vi mọi caller khác); lọc `from`/`to` VẪN theo created_at. **API** `GET /orders` thêm query `sort` (regex `^(created_at|updated_at)$`, default created_at) truyền xuống service. **FE** History thêm `p.set('sort','updated_at')` trong buildParams → đơn vừa CHẠM (đổi trạng thái/thu tiền/sửa) lên đầu. Cô lập: nơi khác không truyền sort → created_at desc như cũ. **TEST** `test_list_sort_updated_at` (tạo a trước/b sau: mặc định b trước a; chạm a → sort=updated_at thì a trước b). Full suite **255 passed**. Build modern+legacy. CSS `index-DSKKIjcR.css` (KHÔNG đổi — stage này không đụng CSS), JS `index-B3cvzVV9.js` (legacy `index-legacy-ComTB44g.js`). **⚠️ CẦN `docker compose restart app`** để kích hoạt param `sort` (BE đổi, KHÔNG migration). TRƯỚC restart: FE gửi `sort=updated_at` nhưng BE cũ BỎ QUA param lạ (FastAPI không 422) → tab Lịch sử vẫn created_at desc, KHÔNG lỗi. Sau restart → updated_at desc.
- [x] Stage 6.46 (3 sửa nhỏ; #1+#2 frontend-only — #3 CHỜ DUYỆT backend). (1) **BỎ nhãn "đã thu" dưới mốc "Nhận đơn"** trong timeline: `buildTimeline` ([lib/timeline.js](pos-pwa/src/lib/timeline.js)) bỏ `sub`/`subOk` (timeline THUẦN trạng thái xử lý — tình trạng thu đã có ở badge); xóa render `.htl__sub` ở CẢ Board.jsx + History.jsx (dùng chung helper) + xóa CSS `.htl__sub*` + bỏ `PAY_SUB`. (2) **Sheet bo CẢ 4 góc**: `.sheet--full` border-radius 16px 16px 0 0 → **16px** (overlay có padding 16 → có khe đáy nên góc dưới hiện); xác nhận sheet **KHÔNG box-shadow** (an toàn Chrome 56). (3) **CHỜ DUYỆT** — sort tab Lịch sử theo updated_at: KHẢO SÁT: `Order` CÓ `updated_at` (UpdatedAtMixin `onupdate=func.now()`, [base.py:39-44](app/models/base.py)) tự cập nhật khi UPDATE (đổi trạng thái/thu tiền/hủy) → **KHÔNG cần migration**; NHƯNG `list_orders` đang **hardcode** `order_by(Order.created_at.desc())` ([order_service.py:578](app/services/order_service.py)) — KHÔNG có tham số sort. → cần đổi backend (đổi mặc định, hoặc thêm param `sort`), KHÔNG migration, nhưng cần `docker compose restart app`. Đã BÁO user chờ chọn cách trước khi sửa (date filter `from`/`to` vẫn lọc theo created_at — kết hợp được: tạo trong 7 ngày, xếp theo lần chạm gần nhất). Build modern+legacy (#1+#2). CSS `index-DSKKIjcR.css`, JS `index-CCn5Q9KT.js` (legacy `index-legacy-CLfWk6aL.js`). Frontend-only, không restart, không test suite.
- [x] Stage 6.45 (Đơn hàng — popup ☰ board thành bottom-sheet ĐẦY ĐỦ + nút In lại bill ở màn pay; frontend-only, 2 commit). **KHẢO SÁT:** (A1) `openSheet` ([Board.jsx:303](pos-pwa/src/pages/Board.jsx)) fetch `GET /orders/{id}` → từ 6.41 trả `tracking`+items+notes+phone → `sheet.full` đủ dựng timeline, KHÔNG cần endpoint mới (đang tải `full=null` → "Đang tải…"). (A2) Cơ chế LÙI ĐÃ CÓ (`move(o,'back')` → patchStatus về cột trước, ghi tracking; card đã disable ← khi colIdx 0) → sheet tái dùng, KHÔNG thêm logic lùi. Pay-first GIỮ (→ dùng move→deliver→`payModal` popup nguyên). **TÁCH HELPER**: `lib/timeline.js` (`buildTimeline`+`PAY_SUB`) dùng chung History + sheet (History bỏ bản local, import). **(B) Bottom-sheet `.sheet--full`** (radius góc trên 16 KHÔNG shadow, overflow-y auto, spacing margin KHÔNG gap, border 1px): tay cầm xám → HEADER (mã 16/500 + badge thu "Đã thu" xanh/"Chưa thu" đỏ + badge trạng thái) → KHÁCH+TIỀN (kẻ trên/dưới: trái "Khách: tên·SĐT", phải Tổng + tag thu) → DỊCH VỤ (items từ full) → GHI CHÚ (tái dùng `.hexp__note--has` nền vàng / `--empty` mờ nghiêng) → TIMELINE ngang 4 bước (tái dùng `.htl*`, từ `full.tracking`) → HÀNH ĐỘNG CHÍNH [← lùi (disable colIdx 0)] [→ tiến, nền cam] flex:1 + [In liên 2] flex 0 0 38% (icon ← → INLINE SVG 20px, BỎ emoji) → HÀNH ĐỘNG PHỤ 5 nút nhỏ flex:1: In bill (printBill)·Chi tiết (/orders/:id)·Thu tiền (/orders/:id/pay)·Hủy đỏ (CANCELLABLE→CancelOrderModal)·Đóng. Nhãn thu binary "Đã thu/Chưa thu" (đồng bộ `PAYMENT_STATUS` paid/unpaid, KHÔNG "Còn nợ"). **(C) OrderPay**: card "✅ đã thu đủ" THÊM nút "In lại bill" → `window.print()`; render `<Receipt order={order}/>` ẩn (Receipt đọc `order.payment_status`='paid' sau thu đủ → in "ĐÃ THANH TOÁN"; `paid`/`method` props Receipt bỏ qua nên chỉ cần order). GIỮ CancelOrderModal/Lien2PrintButton/printBill/pay-first/mọi logic tiền. Verify đọc CSS build (KHÔNG headless). Build modern+legacy. CSS `index-CZ4Wprgk.css`, JS `index-MBXGBDfe.js` (legacy `index-legacy-CtNZCET6.js`). Frontend-only, không restart, không test suite.
- [x] DEPLOY 2026-06-20: đã chạy `alembic upgrade head` (3 migration: a1c2e3f4d5b6 [6.28] + b2d3e4f5a6c7 [6.33] + c3e4f5a6b7d8 [6.37]) + `docker compose restart app` off-peak. Prod ở head `c3e4f5a6b7d8`; OpenAPI live có `OrderDetailOut.tracking` → backend 6.41 ĐÃ LÊN, timeline tab Lịch sử có data thật. **Hết cờ "chờ deploy" của 6.41–6.44.**
- [x] Stage 6.44 (tab Lịch sử — cột Ghi chú nổi bật + đổi mặc định lọc; frontend-only, CSS+JSX): (1) **Cột Ghi chú LUÔN hiện** (bỏ điều kiện ẩn khi trống — `.hexp__col--note` flex 1.4→**1.6**, min-width:0, layout ổn định không nhảy): CÓ note (`od.notes.trim()`) → `.hexp__note--has` **khối nền vàng nhạt** `var(--ns-warn-bg)` + chữ cam đậm `var(--ns-warn)` (token cảnh báo SẴN CÓ, không hardcode), padding 8px 10px, **radius 6** (nhỏ, KHÔNG shadow/overflow → an toàn Chrome 56) — nhân viên thấy ngay đơn có lưu ý; KHÔNG note → `.hexp__note--empty` "Không có ghi chú" xám mờ `var(--muted)` in nghiêng 13px, KHÔNG nền. (2) **Mặc định bộ lọc** khi vào tab: Trạng thái `statusKey` 'delivered'→**'all'** (Tất cả), Ngày giữ **'7d'** → mới vào thấy MỌI đơn 7 ngày qua mọi trạng thái. GIỮ layout 5 cột + timeline + logic mở/đóng/lazy/tìm/lọc/tải-thêm. Verify đọc CSS+JS build (KHÔNG headless). Build modern+legacy. CSS `index-DJTrylzU.css`, JS `index-BuYb2Kyx.js` (legacy `index-legacy-C0VZDxRc.js`). Frontend-only, không restart, không test suite. (Backend 6.41 vẫn cần restart off-peak cho timeline có data.)
- [x] Stage 6.43 (tab Lịch sử — phần mở rộng sang 5 CỘT NGANG; frontend-only, CSS+JSX): **KIỂM:** field note = `orders.notes` (Text), `OrderOut.notes` (schemas/order.py:117) → **OrderDetailOut kế thừa → GET /orders/{id} ĐÃ trả `notes`, KHÔNG cần thêm backend**. **HÀNG 1 = 5 cột flex** (`.hexp__cols` flex-wrap, `align-items:stretch`), ngăn bằng `border-left 1px var(--line)` (`.hexp__col + .hexp__col`; KHÔNG 0.5px, border đơn cạnh không kèm radius → an toàn), `box-sizing:border-box` để bề rộng cố định gồm padding, spacing = padding trong cột (0 12px) KHÔNG flex gap: (1) **Khách hàng** cố định 125px — tên (14/500) + SĐT (13 muted) 2 dòng; (2) **Dịch vụ** `flex:2 1 0` min-width:0 (rộng nhất) — mỗi món 1 dòng (14, lh 1.6); (3) **Ghi chú** `flex:1.4 1 0` min-width:0 — nhãn + `od.notes` (14 muted, word-break) **CHỈ render khi `notes.trim()` có** → trống thì ẩn cột, các cột khác giãn lấp; (4) **Thanh toán** cố định 105px — `PAY_LABEL` (Đã thu/Còn nợ…) + tiền (14/500), xanh `.is-ok`/đỏ `.is-due`; (5) **2 nút** cố định 116px, `justify-content:center`, xếp DỌC (`.btn` width 100%, font 12, padding 7px 8px, `min-height:0`, margin-top 6 giữa) — "In lại bill" + "Xem chi tiết", **chữ thuần KHÔNG icon webfont**. **HÀNG 2** = timeline 4 bước (giữ nguyên 6.42), bọc `.hexp__tl` ngăn hàng 1 bằng `border-top 1px` + padding-top 14. **Hẹp (Sunmi/Chrome 56):** Dịch vụ + Ghi chú co (min-width:0, chữ tự xuống dòng); Khách/Thanh toán/nút giữ cố định; khi tổng quá rộng → `flex-wrap` cột rớt xuống hàng, KHÔNG tràn/đè (máy POS thật là thước đo). Verify đọc CSS build (KHÔNG headless). GIỮ logic mở/đóng + lazy GET /orders/{id} + timeline. Build modern+legacy. CSS `index-f3SmTKk2.css`, JS `index-D6PAiRKQ.js` (legacy `index-legacy-chuKguEZ.js`). Frontend-only, không restart, không test suite. (Backend 6.41 vẫn cần restart off-peak cho timeline có data.)
- [x] Stage 6.42 (tab Lịch sử — LÀM ĐẸP phần mở rộng theo mockup duyệt; frontend-only, CSS+JSX): tăng font + tách dòng + timeline to/đẹp hơn. (1) **Font lớn hơn**: nhãn nhóm 11→**12**, nội dung 13→**14-15**. (2) **Khách hàng 2 DÒNG**: `.hexp__name` (15/600) trên · `.hexp__phone` (14 muted) dưới (bỏ "tên · SĐT" 1 dòng). (3) **Dịch vụ MỖI MÓN 1 DÒNG**: map từng item → `<span.hexp__svc>` (14, line-height 1.7) thay vì `.join(', ')`. (4) **Thanh toán** `.hexp__pay` (15/600): nhãn `PAY_LABEL` (Đã thu/Còn nợ/…) + tiền, tô màu — paid xanh `.is-ok`, nợ/chưa-thu đỏ `.is-due`, refunded trung tính. (5) **TIMELINE to+đẹp**: tiêu đề "Nhật ký thời gian"; chấm 11→**16px** (box-sizing content-box) — done = xanh đặc + **viền 3px MÀU NỀN** `var(--bg)` (tạo chiều sâu/ring, KHÔNG box-shadow), chưa-tới = rỗng viền `--line` + mờ (.is-todo opacity .45), hủy = đỏ; **THANH NỐI LIỀN** thay mũi tên ›: `.htl__link` (flex:0 0 24px) chứa `.htl__bar` (span height **2px** background) — done xanh / chưa-tới `--line` / tới-bước-hủy đỏ `.is-cancel`; căn giữa tâm chấm bằng `margin-top:26` = chiều cao time (line-height 18 + mb 8) khớp `.htl__dotrow` h18 → tâm 35px; giờ TRÊN (13/500 muted), tên DƯỚI (13/500), nhãn thu/nợ (11, xanh/đỏ) dưới "Nhận đơn". (6) **Nút** font 14, min-height 42, margin-left 12 (dễ bấm POS); **KHÔNG icon-font** — mockup vẽ Tabler `ti ti-*` nhưng đó là WEBFONT (vỡ Chrome 56) → giữ nút CHỮ THUẦN. **Chrome 56 an toàn** (đọc CSS build, KHÔNG headless): thanh nối = span height 2px + flex/margin KHÔNG gap; chấm border-radius:50% trên span nhỏ + border, viền trắng/nền bằng BORDER thật KHÔNG shadow; border 1px không 0.5px; không box-shadow khối lớn. GIỮ logic mở/đóng + lazy GET /orders/{id} + map 4 bước + in lại bill. Build modern+legacy. CSS `index-Ch0-YCaD.css`, JS `index-D6jxGgrF.js` (legacy `index-legacy-hU9sH9xs.js`). Frontend-only, không restart, không test suite. (Backend 6.41 vẫn cần `docker compose restart app` off-peak để timeline có data — xem dưới.)
- [x] Stage 6.41 (tab Lịch sử — HÀNG MỞ RỘNG + TIMELINE NGANG; backend read nhỏ + frontend): **KHẢO SÁT (A):** `order_tracking_logs` ghi MỌI lần đổi trạng thái với `created_at` — `_add_tracking` gọi ở create_order (created), change_status (washing/drying/ready/delivered), cancel_order (cancelled) → **đủ 4 mốc + hủy, không cần bổ sung ghi log** (đơn CŨ trước khi có log có thể khuyết mốc → bước khuyết hiện mờ "—"). `GET /orders` (list, OrderOut) đã kèm items + payment_status + customer_phone → info cơ bản KHÔNG cần lazy-load; CHỈ thiếu nguồn timeline → **chọn cách A** (user duyệt). `Receipt({order,config})` tái dùng được cho "In lại bill". **BACKEND (KHÔNG migration):** `OrderTrackingEntry{status,at}` + `OrderDetailOut(OrderOut){tracking:list=[]}`; `order_service.get_order_detail` = `_get_order` + query OrderTrackingLog (asc created_at) → gắn transient `order.tracking=[{status,at}]`; `GET /orders/{id}` đổi response_model OrderOut→**OrderDetailOut** (list GET /orders GIỮ OrderOut, khỏi N query). Test mới `test_get_order_includes_tracking` (created→washing→drying→ready → tracking đúng thứ tự + có `at`). **FE (History.jsx):** ☰ → **chevron** (xoay 180° khi mở, transform OK Chrome 56); bấm dòng → toggle mở (1 đơn/lần, `openId`) + **lazy `GET /orders/{id}`** (cache `details{id}`); đổi lọc → thu hàng. Phần mở rộng `.history__exp` (nền --bg, border-top 1px, KHÔNG radius/shadow/overflow): (a) info ngang wrap (Khách+SĐT · Dịch vụ=items · Thanh toán=nhãn+tiền), (b) **timeline ngang 4 bước** `.htl` (`buildTimeline`: Nhận đơn=created [+nhãn đã thu/nợ] → Đang xử lý=washing|drying SỚM NHẤT → Sẵn sàng=ready → Đã giao=delivered; **đơn hủy** → bước cuối thành "Đã hủy" ĐỎ + giờ hủy; bước chưa có mốc = mờ `.is-todo` opacity.5 + "—"): mỗi bước time(11 muted)·chấm(11px tròn — done xanh đặc/cancel đỏ/chưa-tới rỗng viền --line)·tên(12), nối bằng "›", chia đều `flex:1 1 0`, spacing bằng margin/flex KHÔNG gap, radius CHỈ ở chấm 11px (an toàn — không shadow/overflow). (c) 2 nút chia đôi: "In lại bill" (`window.print()`; `<Receipt order={openOrder}/>` render ẩn cho đơn đang mở → @media print hiện .print-receipt) + "Xem chi tiết đầy đủ" (→ `/orders/:id`). border chuyển từ `.history__row` sang `.history__item` (bọc cả dòng + phần mở rộng). GIỮ logic lọc/tìm/tải-thêm. Full suite **254 passed**. Build modern+legacy. CSS `index-Bwr5G_N5.css`, JS `index-B885TbEh.js` (legacy `index-legacy-mxoEw3b2.js`). **⚠️ BACKEND CẦN DEPLOY**: thay đổi code (KHÔNG migration mới ở stage này) → `docker compose restart app` để `GET /orders/{id}` trả `tracking`; TRƯỚC khi restart, hàng mở rộng vẫn chạy (info cơ bản OK) nhưng **timeline rỗng** (tracking thiếu → mọi bước mờ). Có thể gộp restart cùng off-peak với 3 migration đang chờ (a1c2e3f4d5b6 + b2d3e4f5a6c7 + c3e4f5a6b7d8).
- [x] Stage 6.40 (tab Lịch sử — 1 hàng lọc + dòng đơn 1-dòng-ngang, theo mockup duyệt; frontend-only): (1) **HÀNG LỌC gộp 1 dòng**: `.history__bar` flex — [ô tìm flex:2] [select Trạng thái flex:1] [select Ngày flex:1], margin-left 10 (KHÔNG gap), min-width:0 để co máy hẹp. **Bỏ 8 chip**, thay bằng 2 `<select>` native (hợp Chrome 56): Trạng thái (Đã giao/Tất cả/Đang xử lý/Đã hủy, mặc định **Đã giao**) đặt TRƯỚC Ngày (7 ngày/Hôm nay/Hôm qua/Tháng này, mặc định **7 ngày**). Ô tìm + select min-height 36, font 13. (2) **DÒNG ĐƠN 1-DÒNG-NGANG** (`.history__row` flex căn giữa): mã (đậm 14, min-w 74) · tên (muted 13, flex:1 ellipsis, padding 0 8) · badge (font 11, radius 4) · giờ (muted 11, min-w 74, phải) · tiền (đậm 14, min-w 82, phải) · ☰ (inline SVG `M4 6h16…`, 18px, padding 4 ~tap). padding 9px, kẻ `border-bottom 1px var(--line)` (last bỏ); khung list border 1px + radius 6 (KHÔNG shadow/overflow). **Badge 4 màu**: đã giao xanh (--ns-success) / đã hủy đỏ (--ns-danger) / mới tạo amber (--ns-warn) / đang xử lý cam (--orange-soft/--orange-dark). (3) **CHI TIẾT = ĐIỀU HƯỚNG TRANG** `/orders/:id` (cả dòng + icon ☰), KHÔNG popup — OrderDetail là trang riêng (useParams + window.print + pay/cancel) nên popup sẽ nửa vời/rủi ro. ☰ là dấu hiệu trực quan. (4) Token style mới; **1px KHÔNG 0.5px** (mockup vẽ 0.5px nhưng Chrome 56 làm tròn về 0 → dùng 1px); không box-shadow/flex-gap; overflow:hidden CHỈ ở span tên (ellipsis, an toàn). GIỮ logic lọc/tìm/tải-thêm + mặc định 7 ngày + Đã giao. Build modern+legacy. CSS `index-Co8kauWg.css`, JS `index-Gl5WeHm7.js`. Frontend-only, không restart, không test suite.
- [x] Stage 6.39 (tab Lịch sử — GỌN layout, dày thông tin; frontend-only, CSS-only): tối ưu để thấy nhiều đơn hơn (~6 → ~12-15/màn). (1) **Chip lọc nhỏ**: `.history__filters > .chip` min-height 44→**28px**, radius 999px(pill)→**4px**, border 1px, font 12, `flex:1 1 0` + margin (không gap); chip chọn = nền cam đặc (`.chip--active` sẵn có). Ô tìm thấp lại (min-height **36**, font 13). (2) **List = DANH SÁCH KẺ DÒNG** (thay các thẻ rời): `.history__list` = 1 KHUNG (border 1px + radius 6, KHÔNG overflow:hidden/shadow); `.history__row` bỏ border/radius riêng → `border-bottom:1px var(--line)` (last-child bỏ), padding 8px 12px gọn; dòng 1 mã (14/700)+tiền (phải), dòng 2 tên (12 muted)+badge+giờ (margin-top 2px). Badge `.hbadge` font 11/radius 4. (3) "X đơn" font 12 muted. (4) Token đúng style mới (var(--line)/--orange/--muted/--ink), radius 6 khung/4 control, KHÔNG box-shadow/0.5px/flex-gap; chỉ overflow:hidden trên span ellipsis tên khách (an toàn — không kèm radius/shadow). GIỮ logic lọc/tìm/tải-thêm/bấm-đơn. Build modern+legacy. CSS `index-DOCjtKFo.css`, JS `index-4v2D904p.js`. Frontend-only, không restart, không test suite.
- [x] Stage 6.38 (TAB LỊCH SỬ — gộp Tra cứu; frontend-only, KHÔNG cần backend mới): KHẢO SÁT: `GET /orders` (list_orders) ĐÃ hỗ trợ `from`/`to` (lọc `created_at`), `order_status[]`, `payment_status[]`, `q` (search mã/tên/SĐT qua `_apply_search`), phân trang limit/offset, sort `created_at desc` → KHÔNG cần endpoint mới. Tra cứu cũ = `pages/OrderSearch.jsx` (route /search) gọi đúng endpoint đó. **TẠO `pages/History.jsx`** (style mới `.history__*` + `.hbadge--*`, radius 6/4, kẻ 1px, spacing `> * + * margin` KHÔNG gap, không shadow): ô tìm (mã/tên/SĐT, mọi đơn) + 2 hàng chip lọc nhanh (flex:1 1 0 + margin): **Thời gian** (Hôm nay/Hôm qua/7 ngày/Tháng này — tính `from`/`to` theo giờ VN qua `startOfDayVn`/`addDaysVn`/`vnWallToISO`; mặc định **7 ngày**) + **Trạng thái** (Tất cả/Đang xử lý/Đã giao=delivered+completed/Đã hủy=cancelled; mặc định **Đã giao** — đơn đã đóng, không lặp tab Đơn hàng). ĐANG GÕ tìm → BỎ QUA lọc (tìm toàn bộ). Danh sách (mới nhất trước): mã + tên + tiền + **badge trạng thái màu** (giao xanh `--ns-success` / hủy đỏ-xám / đang xử lý cam `--ns-warn`) + giờ (`formatPickupBoard`: hôm nay→giờ, khác ngày→DD/MM HH:MM); bấm → `/orders/:id` (OrderDetail). Phân trang "Tải thêm" (offset). Tổng kết: chỉ **"X đơn"** (total từ API) — **TỔNG TIỀN (Y) BỎ QUA**: cần backend aggregate (sum theo filter) → tách stage sau nếu cần. **DỌN:** nav `/search` "Tra cứu" → `/history` "Lịch sử" (Layout); App.jsx `/history`→History, `/search`→Navigate `/history` (redirect, không gãy link); XÓA `OrderSearch.jsx` (đã gộp hết). Build modern+legacy. CSS `index-CkOPAGPa.css`, JS `index-sk7uE6p0.js`. Frontend-only, không restart, không test suite (backend không đụng). **CẦN BACKEND SAU (tùy chọn)**: endpoint/aggregate tổng tiền theo bộ lọc cho dòng "tổng Y".
- [x] Stage 6.37 (TÀI CHÍNH — MỞ LẠI CA reopen + xem/in lại ca đã đóng; test-first): khách tới muộn sau khi đã đóng ca → mở lại ca vừa đóng để thu tiếp rồi đóng lại. **BACKEND:** (A) **migration `c3e4f5a6b7d8`** (← b2d3e4f5a6c7): `shifts.reopen_count` (Integer NOT NULL default 0). **`POST /shifts/{id}/reopen`** → `reopen_shift`: chỉ ca status='closed' (else 409 `SHIFT_NOT_CLOSED`), branch chưa có ca mở khác (else 409 `SHIFT_ALREADY_OPEN`, + IntegrityError race → 409), và **chỉ ca ĐÓNG GẦN NHẤT** của branch (else 409 `CANNOT_REOPEN_NOT_LATEST`). Đảo về 'open': XÓA số chốt (closed_at/by, closing_cash_expected/actual, cash_difference, cash_diff_reason, handover_to_owner, cash_left_for_next, total_*, orders_count), **GIỮ opening_cash + mọi payment/cash_transaction** (sổ tiền bất biến); `reopen_count += 1`. Đóng lại → `close_shift` tính mới gồm cả khoản thu thêm (sổ cân). **LOG**: ghi `audit_logs` (action='shift.reopen', entity_type='shift', entity_id, user_id, new_data_json) — **dùng bảng audit_logs SẴN CÓ, không migration cho log** (migration chỉ cho reopen_count để FE/owner hiển thị nhanh). (B) `GET /shifts/latest-closed` (mới, đặt TRƯỚC /{id}) → ca đóng gần nhất (cho xem/in lại từ DB); `GET /shifts/{id}` đã có sẵn. (4) owner_summary cash_diff rows + `CashDiffRow` +`reopen_count`; ShiftOut +`reopen_count`. **FE (Shift.jsx):** (6) ResultCard BỎ icon 🧾 ở 2 nút in; THÊM nút "Mở lại ca" (viền amber `.shift__reopen`, không phải nút chính) → popup `.panel` xác nhận ("…được ghi log") → `doReopen` POST reopen → về màn ca đang mở; hiện "Ca này đã mở lại N lần" nếu reopen_count>0. (7) **FIX refresh mất biên nhận**: màn "chưa có ca" nếu có ca đóng gần nhất (`GET /shifts/latest-closed` trong loadCurrent nhánh 404) → nút "Xem ca vừa đóng" → ResultCard đọc TỪ DB (không state tạm) → in lại biên nhận bất cứ lúc nào + mở lại được. (Lưu ý: bảng bàn-giao của biên bản giao ca là snapshot lúc đóng, KHÔNG lưu → khi xem lại để trống; biên nhận nộp chủ = số liệu ca → in lại đủ.) **TEST (viết trước):** reopen→thu thêm→đóng lại (chốt xóa, payment giữ, sổ cân gồm khoản mới), 409 (chưa đóng / có ca mở / không phải đóng-gần-nhất), audit_log có ghi (ai/ca). Full suite **253 passed**. Build modern+legacy. CSS `index-Cbp-eIGC.css`, JS `index-CuoVNw5t.js`. **⚠️ DEPLOY off-peak: `alembic upgrade head` (gồm 3 migration chưa chạy: a1c2e3f4d5b6 [6.28] + b2d3e4f5a6c7 [6.33] + c3e4f5a6b7d8 [6.37]) + `docker compose restart app`.** Migration cho phần LOG: KHÔNG cần (audit_logs sẵn có) — chỉ cần migration cho reopen_count.
- [x] Stage 6.36 (UI màn ĐÓNG CA — 2 chỉnh nhỏ, nhất quán 6.35; frontend-only): (1) **Lỗi "Lý do lệch tiền" → DƯỚI Ô** (như lỗi rút nộp chủ 6.35): bỏ `setError('Vui lòng nhập lý do lệch tiền.')` ở đầu màn → state `reasonErr`; submit khi diff≠0 mà ô trống → `setReasonErr(true)`; hiện `<span class="field-note field-note--err">Vui lòng nhập lý do lệch tiền.</span>` ngay dưới textarea; gõ ô (onChange) → clear; đổi `actual` (đếm lại) cũng clear (tránh lỗi cũ hiện lại khi diff đổi). Lỗi KHÁC giữ ở đầu màn. Backend vẫn chặn 422 CASH_DIFF_REASON_REQUIRED (6.33) — đai an toàn không đổi. (2) **DÒNG CHỮ cảnh báo lệch → ĐỎ mọi mức**: `.shift .diff--warn .diff__note, .shift .diff--danger .diff__note { color: var(--danger) }` (warn vốn amber → ép đỏ). Số "Chênh lệch" GIỮ màu theo mức (6.31). Verify soi build: note warn/danger đỏ, field-note--err đỏ, 0 chỗ 0.5px/gap/shadow. Hash JS `index-D6FpGg4I.js`, CSS `index-C8Zr-tC8.css`. Frontend-only, không restart, không test suite (backend không đụng).
- [x] Stage 6.35 (UI màn ĐÓNG CA — 4 chỉnh; frontend-only, gọn chiều cao + lỗi đúng chỗ): (1) **BỎ dòng COD** ở "Đã thu trong ca" (tiệm chưa có COD). (2) **GỘP "Chuyển khoản"+"QR" → 1 dòng "Chuyển khoản & QR"** = `totals.transfer + totals.qr`. (1+2: thay `METHODS.map` ở form đóng ca bằng 2 dòng tường minh Tiền mặt / CK&QR — bớt 2 dòng; METHODS giữ nguyên cho phiếu giao ca.) (3) **Lỗi "rút nộp chủ trống" → DƯỚI Ô, gộp ghi chú** (bỏ báo ở đầu màn): state `handoverErr`; submit ô trống → `setHandoverErr(true)` (KHÔNG `setError` đầu màn); ghi chú dưới ô = xám "Nhập 0 nếu không rút tiền nộp chủ." bình thường, chuyển **đỏ** + đổi chữ "Vui lòng nhập số tiền nộp chủ (nhập 0 nếu không rút)." khi lỗi (class `.field-note--err`); gõ lại ô → clear lỗi (onChange). Lỗi KHÁC (lý do lệch, handover>actual, close fail) GIỮ ở đầu màn. (Ghi chú: `.field .field-note` vốn đã xám `--muted` từ 6.34 — không dính style đỏ; chỉ thêm biến thể `--err`.) (4) **GỌN CHIỀU CAO** (vừa 1 màn POS, đỡ cuộn tới nút): `.shift .card` padding 14→12; `.card__title` mb 10→8; `.summary` padding 8→6/mb 12→8; `.summary__row` 4→3; `.field` mb 12→8; `.diff` padding 8→6/margin 12→8. GIỮ logic đối soát + tiền để lại + validate (rút nộp chủ bắt buộc, lý do lệch) + đóng ca; ô nhập vẫn cuộn được khi bàn phím ảo (trang cuộn). Verify soi build: `.field-note--err` đỏ, note thường xám, card padding 12, 0 chỗ 0.5px/gap/shadow. Hash JS `index-ChEhkpi8.js`, CSS `index-BeMx3a6f.css`. Frontend-only, không restart, không test suite (backend không đụng — summary client-side, close_shift giữ nguyên).
- [x] Stage 6.34 (UI 2 ô tiền màn ĐÓNG CA — frontend-only): (1) **BÀN PHÍM SỐ trên máy POS Chrome 56**: `MoneyInput` đổi `type="text"`→**`type="tel"`** (giữ `inputMode="numeric"`). Lý do: `inputmode` không đáng tin trên Android 6/Chrome 56 (modern inputmode từ Chrome 66); `type="tel"` LUÔN bật keypad số trên máy cũ và CHO ký tự text → KHÔNG phá format dấu chấm "3.100.000" (khác `type="number"` cấm '.'). Áp cho MỌI MoneyInput (đóng ca, mở ca, thu tiền, hoàn tiền) — đều là ô tiền nên đúng. Logic format/parse giữ nguyên (onChange strip \D → số thuần). (2) **"Rút nộp chủ" BẮT BUỘC nhập (FE)**: `submitClose` chặn khi `handover === ''` (chưa nhập gì) → lỗi "Vui lòng nhập số tiền nộp chủ (nhập 0 nếu không rút)." — phân biệt "đã xác nhận 0" vs "quên điền"; nhập 0 hợp lệ (đóng OK). Thêm ghi chú `<span class="field-note">Nhập 0 nếu không rút tiền nộp chủ</span>` dưới ô (muted 11px; class mới `.field .field-note` đè `.field > span`). Backend KHÔNG đổi (0 hợp lệ; đây là ràng buộc thao tác, không phải chống gian lận). GIỮ logic đối soát + "tiền để lại ca sau" + đóng ca. Verify soi build: `type:"tel"` trong JS, `.field .field-note` trong CSS. Hash JS `index-CCf4VMgN.js`, CSS `index-D0D53s48.css`. Frontend-only, không restart, không test suite (backend không đụng).
- [x] Stage 6.33 (TÀI CHÍNH — LƯU + BẮT BUỘC lý do lệch tiền khi đóng ca; test-first; nối tiếp FE 6.32): persist `cash_diff_reason` + đai an toàn backend (lớp 2 sau FE). (1) **MIGRATION `b2d3e4f5a6c7`** (down_revision a1c2e3f4d5b6): thêm cột `shifts.cash_diff_reason` (Text, nullable) — additive an toàn. (2) **SCHEMA**: `ShiftClose` +`cash_diff_reason: str|None=None` (max 500); `ShiftOut` +`cash_diff_reason`. (3) **SERVICE `close_shift`**: nhận `cash_diff_reason`; tính `cash_difference` rồi **ĐAI AN TOÀN**: nếu `cash_difference != 0` mà reason None/rỗng/space → raise **422 `CASH_DIFF_REASON_REQUIRED`** TRƯỚC khi đổi field (ca giữ 'open', không đóng nửa vời); diff=0 → cho None; lưu `shift.cash_diff_reason = reason or None`. Endpoint truyền `payload.cash_diff_reason`. (4) **owner_summary**: thêm `Shift.cash_diff_reason` vào select + row mục cash_diff + `CashDiffRow` schema +`cash_diff_reason`; **FE Reports.jsx** hiện "Lý do: …" dưới mỗi ca lệch (dùng `.reports__list-meta`). **TEST (viết trước):** `test_close_diff_without_reason_422` (lệch thiếu lý do → 422 + ca VẪN open; cả chuỗi khoảng-trắng), `test_close_diff_with_reason_saved` (lưu đúng DB), `test_close_matched_no_reason_ok` (diff=0 không bắt). Sửa test cũ đóng-ca-lệch: `test_close_mixed_methods` (diff 5000) + `test_telegram._open_close` thêm param reason (`test_close_large_diff_warns`). Full suite **248 passed**. Build modern+legacy (FE Reports). **⚠️ DEPLOY off-peak (migration TRƯỚC, restart SAU như 6.28): `alembic upgrade head` (rev b2d3e4f5a6c7) + `docker compose restart app`.** FE đã gửi cash_diff_reason từ 6.32 → sau restart là persist + chặn được tầng backend.
- [x] Stage 6.32 (UI màn ĐÓNG CA — 3 chỉnh; FE-only, màn tài chính): (1) **"Tiền để lại ca sau" tách 2 dòng**: dòng chính `.cashleft__main` (nhãn + CON SỐ kết quả to/đậm/cam `var(--orange)` 20px) + dòng phụ `.cashleft__calc` (phép tính `actual − handover`, 12px `--muted`). `.shift .cashleft` đổi flex-1-dòng → block 2 dòng; giữ `--bad` → số đỏ khi nộp chủ vượt thực đếm. (2) **Lý do lệch tiền BẮT BUỘC khi lệch≠0**: textarea `.field` hiện khi `level∈{warn,danger}` (diff≠0); submit chặn nếu thiếu (`setError('Vui lòng nhập lý do lệch tiền.')`); khớp két (diff=0) → không hiện/không bắt. **⚠️ BACKEND CÒN THIẾU (FE-only stage này): shift KHÔNG có cột `cash_diff_reason`, `ShiftClose` schema không nhận → FE gửi `cash_diff_reason` trong body nhưng Pydantic BỎ QUA (extra ignored) → CHƯA LƯU.** Cần (xử riêng, có migration): thêm cột `shifts.cash_diff_reason` (Text null) + field vào `ShiftClose` + lưu ở `close_shift` service. FE đã forward-compat (gửi sẵn). (3) **Đổi text cảnh báo**: gộp warn+danger → cùng chữ "⚠️ Lệch tiền, kiểm đếm lại trước khi xác nhận" (bỏ phân biệt "nhỏ/lớn" trong CHỮ); GIỮ màu theo mức (note amber/đỏ + số chênh lệch màu theo level từ 6.31) + GIỮ lưu `cash_difference` thật (chỉ đổi chữ). GIỮ logic đối soát/đóng ca. Verify soi CSS build: cashleft block 2 dòng (số cam 20 / calc muted 12), 0 chỗ 0.5px/gap/shadow. CSS hash `index-BeSFoMer.css`. Frontend-only, không restart.
- [x] Stage 6.31 (UI màn ĐÓNG CA — frontend-only, CSS-only, KHÔNG đổi JSX/logic; màn tài chính): nối tiếp 6.29/6.30. Phần lớn đã theo style mới từ 6.29 (`.shift .card/.summary/.field/.input` radius 6, kẻ 1px, bỏ shadow). Stage này: (1) **Khối đối soát `.diff`** ("Dự kiến/Thực đếm/Chênh lệch") đổi từ KHUNG-MÀU (border 1.5px + nền theo level) → **KẺ 1px trên+dưới, không nền** (`.shift .diff` background/border none + border-top/bottom 1px var(--line), radius 0); GIỮ tín hiệu lệch bằng **MÀU CHỮ** dòng Chênh lệch (`.shift .diff--ok/warn/danger .diff__line--total strong` xanh/cam/đỏ) + note màu (sẵn) → không mất cảnh báo sai số/gian lận. (2) **"Tiền để lại ca sau" `.cashleft`**: BỎ khung/nền/viền cam → typography (`.shift .cashleft` background/border none; con số `strong` **18px/800 màu --orange**; `--bad` → số đỏ khi nộp chủ vượt thực đếm). (3) **`.shift__empty`** (màn "chưa có ca"): bỏ box-shadow + radius 14→6 (đồng bộ, bonus). **ĐÃ CÓ SẴN, không sửa:** format nghìn khi gõ + không prefill "000" (MoneyInput dùng cho cả "thực đếm" + "rút nộp chủ" — Intl vi-VN, lưu số thuần) (#3); KHÔNG nút gợi-ý-số cho ô thực đếm (cố ý — buộc đếm thật chống gian lận) (#4); 2 ô nhập mỗi ô 1 `.field` riêng dòng (#5); bàn phím ảo không che (close form là trang cuộn `.app-main` flex:1, không modal khoá-giữa → ô nhập tự scroll vào tầm khi focus) (#6). GIỮ toàn bộ logic đối soát + xác nhận đóng ca. Verify soi CSS build: `.shift .diff` kẻ 1px no-box, cashleft cam typography, shift__empty no-shadow, rule mới 0 chỗ 0.5px/gap/shadow. CSS hash `index-BRNHHHAU.css`. Frontend-only, không restart.
- [x] Stage 6.30 (UI tab Ca — frontend-only, 3 chỉnh; dùng `.panel/.shift` của 6.29; KHÔNG đổi logic): (1) **BỎ icon** ở các dòng chỉ số main view (💵🏦📊) + 🔄 ở nút Làm mới — chỉ giữ chữ. (2) **"Tiền mặt trong két"**: BỎ khung/nền/viền cam (`.metric--hero` cũ = orange-soft bg + 1.5px orange border + radius 10) → nổi bằng **TYPOGRAPHY** (`.shift .metric--hero` override: background/border/radius none; label 14/800 màu --ink; **value 22px/800 màu --orange**) → hoà vào nhóm, nổi nhờ cỡ+đậm, không hộp. (3) **Bố cục nút 2→3 nút, 2 hàng**: trên `+ Tạo đơn` (btn--primary cam full, `.shift__cta` min-height 48 — thấp hơn xl 64 cũ, font 17/800); dưới `.shift__btnrow` 2 nút viền 50/50 (`btn--ghost btn--sm`, `flex:1 1 0`, khe `> * + * margin-left:10px` KHÔNG gap): "Đơn hàng" → `navigate('/board')`, "Đóng ca" → `setView('close')` (viền thường, không cam, tránh bấm nhầm). radius 4 (qua `.shift .btn`). GIỮ: logic mở/đóng ca + đối soát + realtime, nhãn "Doanh thu ca (dự kiến)". Verify soi CSS build: hero `background:none` + value cam 22; `.shift__cta` 48; `.shift__btnrow` margin (không gap); rule MỚI 0 chỗ 0.5px/gap/shadow. (Ghi chú: `.shift__empty` — màn "chưa có ca" — vẫn shadow+radius14 cũ, NGOÀI 3 chỉnh này, chưa đụng.) CSS hash `index-B9U_7kBF.css`. Frontend-only, không restart.
- [x] Stage 6.29 (UI đồng bộ "style mới" — frontend-only, KHÔNG đổi logic): tạo **bộ class CHUNG `.panel`** (index.css) theo quy ước cfm (màn Xác nhận đơn) để đồng bộ toàn app + an toàn Chrome 56. Đặc tính: panel radius **6px** / control radius **4px**; **KHÔNG box-shadow**; phân nhóm bằng **kẻ 1px var(--line)** (không hộp bo to); spacing bằng **`> * + * {margin}`** (KHÔNG flex gap); **border 1px** (KHÔNG 0.5px); token `--line/--orange/--orange-dark/--muted/--danger/--surface/--bg` (KHÔNG `--ns-*`, KHÔNG `var(--radius)=14`). Class: `.panel` (+`--modal` width 440/max-height vh), `.panel__head/__title/__spacer/__body` (body cuộn nội bộ — bàn phím ảo), `.panel__group` (+`-title`, phân cách kẻ 1px), `.panel__row` (+`--strong`), `.panel__foot` (nút chia đều), `.panel__hint` (+`--danger`) (dòng nhắc cam/đỏ nền nhạt), + override control trong panel (`.panel .input/.btn/.field/.chip` → radius 4, input 34/13, label 11, nút 38). **ÁP (B) CancelOrderModal**: bỏ `.modal` cũ (radius 14/shadow/font 19/input 18) → `.panel panel--modal` + overlay `modal-overlay--top` (neo trên + body cuộn → ô nhập KHÔNG bị bàn phím ảo che, Sunmi màn ngang); THÊM dòng nhắc tách-đơn (`.panel__hint` cam) khi đơn **CHƯA thu + order_status≠'created'** (đã làm dở → khuyên hủy rồi tạo đơn mới thu đúng); giữ logic hủy/hoàn/sổ-cân. **ÁP (C) Shift (tab Ca)**: page-scope `.shift .card/.summary/.metrics-group/.metric/.diff/.field/.input/.btn` → radius 6, bỏ shadow, font 13-15, kẻ 1px, gọn chiều cao — **KHÔNG đổi cấu trúc JSX** (bảo toàn logic mở/đóng ca + đối soát; Shift là trang cuộn nên ô nhập tự scroll vào tầm khi focus). Giữ nhãn "Doanh thu ca (dự kiến)". Verify soi CSS build (KHÔNG headless): `.panel` radius6/border1/no-shadow, `.shift .card` box-shadow:none, **0 chỗ 0.5px / flex-gap / box-shadow** trong rule mới. CSS hash `index-DHkgvley.css`. Frontend-only, không restart. **TEST MÁY POS**: modal Hủy + tab Ca theo style mới, ô nhập không bị bàn phím che.
- [x] Stage 6.28 (TÀI CHÍNH — thiết kế lại HỦY ĐƠN cho sổ LUÔN CÂN; test-first): trước đây `cancel_order` chỉ set order_status='cancelled' → đơn ĐÃ THU bị hủy thì doanh thu rớt −T nhưng tiền vẫn trong két/total_collected → LỆCH SỔ (khe thất thoát). **NGUYÊN TẮC SỔ:** doanh thu của đơn HỦY = tiền THỰC GIỮ LẠI = (đã thu − đã hoàn) = **net payments** của đơn; KHÔNG còn loại sạch đơn cancelled khỏi doanh thu. **BACKEND:** (1) Order +`cancel_reason` (Text, bắt buộc enforce ở service) +`refund_amount` (Money, default 0) — migration `a1c2e3f4d5b6` (down_revision f0a1b2c3d4e5). (2) `cancel_order(db, actor, id, *, cancel_reason, refund_amount=0)`: validate transition (chỉ hủy TRƯỚC delivered) → 422 `CANCEL_REASON_REQUIRED` nếu thiếu lý do → `refund_amount` 0..paid_sum (net), vượt → 422 `REFUND_EXCEEDS_PAID`; nếu refund>0 ghi **cancel_paid ÂM (cash)** qua `payment_service._record_payment` (tách KHÔNG-commit từ `create_payment` để gộp refund + đổi trạng thái CÙNG 1 transaction → nguyên tử, tránh refund-mà-chưa-hủy/double-refund) tham chiếu payment dương gần nhất; rồi set order_status='cancelled'+cancel_reason+refund_amount, commit. Hoàn LUÔN tiền mặt ra két (payment cancel_paid cash âm → `pay.cash` giảm → cash_in_drawer & total_collected tự giảm; KHÔNG tạo thêm cash_transaction để tránh trừ 2 lần). (3) **DOANH THU** (shift_service.shift_summary + report_service.owner_summary): đổi `SUM(total_amount) WHERE status!=cancelled` → contribution `CASE WHEN status!=cancelled THEN total_amount ELSE COALESCE(net payments,0)` (LEFT JOIN tổng payments/đơn). order_count vẫn chỉ đếm đơn không hủy. (report: mục "nợ chưa thu" GIỮ `base_order_conds` loại cancelled — chỉ doanh thu đổi). (4) Endpoint: `DELETE /orders/{id}` → **`POST /orders/{id}/cancel`** body `OrderCancel{cancel_reason, refund_amount}`. **TEST (viết trước):** 4 ca sổ-cân (chưa thu / đã thu hoàn tất cả→refunded / hoàn một phần / không hoàn) đều assert `shift_revenue == total_collected` + két khớp; reason bắt buộc 422; refund>đã thu 422; sửa test cancel cũ (delete→POST cancel + reason, kể cả test_board_grouping). Full suite **245 passed**. **FRONTEND:** `components/CancelOrderModal.jsx` (mới, dùng chung) — lý do bắt buộc + (nếu đã thu) ô "Hoàn cho khách" 0..đã-thu mặc định hoàn tất cả + hiện "Giữ lại"; tự fetch net payments. OrderDetail: bỏ confirm-inline 2 bước → nút "Hủy đơn" mở modal. Board ☰: thêm "Hủy đơn" (đỏ, chỉ khi status created/washing/drying/ready) → modal → toast + reload. **GIỮ** UI "Hoàn tiền" rời ở OrderDetail (mục đích KHÁC: hoàn tiền KHÔNG hủy, vd khiếu nại sau giao — refund_amount cancel bị chặn ≤ net nên không double). Đổi nhãn Shift "Doanh thu ca" → "Doanh thu ca (dự kiến)" (chỉ label). Build modern+legacy OK. **⚠️ DEPLOY off-peak: `alembic upgrade head` + `docker compose restart app` (backend đổi + migration). FE đã live (dist) — nút Hủy sẽ 404 tới khi restart app.**
- [x] Stage 6.9.12: nhãn liên 2 thêm SỐ TIỀN — CHỈ đơn CHƯA thanh toán (unpaid). `Lien2LabelBody`: `{!paid && <div className="lbl__amt">{formatVND(order.total_amount)}</div>}` ngay DƯỚI dòng trạng thái "CHƯA THANH TOÁN / UNPAID" (đơn paid KHÔNG in — đã thu). Format `formatVND` (lib/format.js) → "100.000đ" (vi-VN dấu chấm nghìn + đ). CSS `.lbl__amt`: canh giữa, font-weight 800, font-size 20px (nhỏ hơn Time 23px), margin-bottom 8px (khe trên do .lbl__pay margin-bottom lo → đơn paid giữ nguyên spacing). Không đổi gì khác. Build modern+legacy. Full suite 236.
- [x] Stage 6.10: dashboard "Đơn hàng" → 3 CỘT thao tác (FE-only). Thanh trên cùng GỘP 1 dòng 48px (style mới: kẻ 0.5px + palette dịu, token `--ns-*`): tabs · SLOT controls của trang (search nhỏ + Làm mới portal qua context mới `TopbarSlotContext`) · BỘ CHỌN CN DÙNG CHUNG (đưa vào Layout, owner LUÔN hiện, có option "Tất cả CN") · ☰. Bỏ hàng chip CN cũ; Board.jsx + Shift.jsx (màn Ca) chuyển sang `useBranch()` (1 nguồn cho mọi màn) — CashBook/Reports giữ chip riêng đợt này (migrate sau). 3 cột ĐỀU NHAU `flex:1`, KHÔNG cuộn ngang: Mới nhận / **Đang xử lý (GỘP washing+drying)** / Sẵn sàng; BỎ cột "Đã giao" (tra ở tab Tra cứu — 6.11). Lưới thẻ `grid repeat(auto-fit,minmax(120px,1fr))` trong `@supports (display:grid)` + fallback `flex-wrap` (`flex:1 1 120px`) cho Chrome cũ Sunmi. THẺ = KHUNG RỖNG (52px, click→chi tiết đơn; layout thẻ + thao tác nhanh ← → ☰ thiết kế stage sau). Dòng thống kê 1 dòng mảnh (Ở tiệm/Chưa thu/Đã thu/Nợ — tính CLIENT từ đúng 3 cột hiển thị → KHÔNG gồm delivered; BỎ "Trễ hẹn") + "Cập nhật HH:MM" dồn phải. BỎ chế độ Bảng/Danh sách. Backend `get_board` KHÔNG đổi. Build modern+legacy. Full suite 236. **CẦN TEST SUNMI**: 3 cột vừa khít không cuộn ngang + auto-fit reflow trên Chrome thật.
- [x] Stage 6.11: tab "Tra cứu" — tìm MỌI đơn (mọi trạng thái, mọi ngày) theo mã đơn / tên khách / SĐT. **CODE-ONLY, KHÔNG migration/DB** (phone & order_code đã có index sẵn; ILIKE substring không dùng btree nên không thêm index — pg_trgm để dành lúc scale 50-100 CN). Backend: mở rộng `_apply_search` (order_service.py) thêm `Customer.phone.ilike(like)` vào `or_(order_code, full_name, phone)` → 1 ô search match cả 3 trường (ảnh hưởng cả `/orders` và `/orders/board`). TÁI DÙNG `GET /orders` (đã có phân trang limit/offset + lọc tenant/branch + order_status/payment_status/date). Frontend: `pages/OrderSearch.jsx` (mới) + route `/search` + tab "Tra cứu" (Layout NAV) + dùng `useBranch()`. UI style mới (0.5px): 1 ô search (debounce) + chip lọc TT + dropdown trạng thái; **KHÔNG tự fetch khi rỗng** (tránh tải hết DB) — chỉ tra khi có từ khoá/bộ lọc; kết quả mỗi đơn: mã, tên+SĐT, trạng thái đơn, tổng tiền, badge TT, ngày tạo + ngày giao; phân trang "Tải thêm" (offset, 25/trang); click → màn chi tiết `/orders/:id` (tái dùng). Test `tests/test_orders.py::test_list_search_q_by_phone`. Build modern+legacy. Full suite 237. **LƯU Ý DEPLOY**: backend cần `docker compose restart app` (uvicorn không --reload) để áp tìm theo SĐT; frontend (nginx serve dist) đã live sau build. **CẦN TEST SUNMI**: tra theo SĐT/tên/mã + phân trang.
- [x] Stage 6.12: THẺ Kanban thao tác — lấp "khung rỗng" của 6.10 (frontend chính + 2 field backend nhỏ). (Spec gửi nhãn "Stage 3.8" nhưng thực chất là phần thiết kế thẻ mà 6.10 hoãn; đổ vào layout 3 cột HIỆN TẠI, KHÔNG quay lại 5 cột/cột Đã giao.) **Backend** (payment_service): ghi nợ BẮT BUỘC `reason` → 422 DEBT_REASON_REQUIRED (debt VẪN amount=0 theo quy tắc tài chính; KHÔNG có method='debt' — đó là transaction_type). + thêm `notes` vào schema `BoardOrder` (cho icon ghi chú; không kèm items; KHÔNG migration). Test `test_debt_requires_reason` + sửa `test_debt_then_resolve` (kèm reason). **Frontend** (Board.jsx): mỗi thẻ = order_code+tên / tổng tiền+badge TT (debt='NỢ' tím) / giờ hẹn HH:MM DD/MM + cờ TRỄ (góc phải đỏ) + 📝 khi có notes; viền trái màu theo payment_status. Nút ← → đổi trạng thái (PATCH /orders/{id}/status, cập nhật LẠC QUAN + revert + toast; ← ẩn ở created). "ready →" = giao: server đổi delivered rồi cờ requires_payment → mở POPUP GIAO‑THU tại chỗ: "Còn phải thu {tiền}" + chọn Tiền mặt/Chuyển khoản + (a) "Thu đủ" (POST payment amount=còn lại) (b) "Ghi nợ" (ô lý do BẮT BUỘC → POST debt amount=0 + reason). KHÔNG nút "Bỏ qua": đóng popup → LÙI delivered→ready (đơn chưa thu được phép) → chống thất thoát. Sau xử lý: auto_print BẬT → in bill (Receipt + window.print). Menu ☰ = bottom sheet: Xem chi tiết / In lại bill / In liên 2 (tái dùng Lien2PrintButton; fetch full order khi mở). Build modern+legacy. Full suite 238. **LƯU Ý DEPLOY**: 2 field backend cần `docker compose restart app`. **CHƯA chạy luồng giao→thu/nợ trên DB prod** (payment immutable — không tạo dữ liệu giả); xác minh bằng pytest + render popup MOCK API. **CẦN TEST SUNMI**: nút ← →/popup giao‑thu/menu ☰ trên máy thật.
- [x] Stage 6.13: PAY‑FIRST khi giao đơn (FRONTEND-ONLY, KHÔNG đụng backend/test) — vá khe thất thoát của 6.12. **Vấn đề cũ:** bấm → ở 'ready' → PATCH delivered NGAY rồi mới mở popup; đóng popup thì cố lùi delivered→ready với `catch` RỖNG → nếu lùi lỗi / mất mạng / đóng app giữa chừng / GET payments lỗi → đơn KẸT delivered‑CHƯA‑THU (vô hình vì board không có cột delivered). **Nay** (Board.jsx `deliver`/`finishDeliver`/`dismissPay`): đọc `payment_status` của thẻ — paid/debt/refunded → PATCH delivered thẳng; unpaid/partial → MỞ POPUP NGAY, **CHƯA PATCH gì** (đơn vẫn 'ready' trên server). "Thu đủ"/"Ghi nợ" THÀNH CÔNG → **mới** PATCH delivered. **Đóng popup = chỉ setPayModal(null), KHÔNG gọi server lần nào** (bỏ hẳn cơ chế "lùi"). PATCH cuối lỗi → KHÔNG nuốt lỗi: toast "Đã thu tiền/Đã ghi nợ, nhưng chưa cập nhật trạng thái — bấm lại để giao" (đơn ở 'ready' đã paid/debt → bấm lại được). ⇒ đơn KHÔNG BAO GIỜ ở delivered khi chưa xử lý tiền (xoá khe W1/W2/W3). Cờ `requires_payment` KHÔNG còn dùng ở FE (quyết bằng `payment_status`). Tự kiểm MOCK API (không chạy tiền thật trên prod), **5 nhánh PASS**: paid→thẳng / unpaid→popup‑chưa‑PATCH / dismiss→0 call server / thu‑xong→payment‑trước‑PATCH / PATCH‑lỗi→toast‑đúng. Build modern+legacy. Backend/test KHÔNG đổi (suite vẫn 238). **KẾ HOẠCH STAGE SAU (B):** `change_status` từ chối delivered khi `payment_status ∈ {unpaid,partial}` → 409 `PAYMENT_REQUIRED_BEFORE_DELIVERY`; sửa ~8 test sang pay‑first; BỎ cờ `requires_payment` (thay bằng 409) → đai an toàn tầng DB, hết 2 cơ chế song song. **CẦN TEST SUNMI**: 4 luồng giao‑thu trên máy thật.
- [x] Stage 6.14: THẺ Kanban — MẪU CHUẨN (FRONTEND-ONLY, theo `the-don-kanban-mau.html`). Áp hình thức thẻ chuẩn lên Board.jsx: viền trái 3px (xanh #0f6e56 = ĐÃ THU đủ / đỏ #a32d2d = CÒN NỢ tiền: unpaid+partial+debt / xám = hoàn), radius `0 8px 8px 0`. Dòng 1: mã đơn (16px,600) + icon ghi chú (cam, CHỈ khi có notes, BẤM → popup ghi chú) + tên khách (13px, ellipsis 1 dòng, căn phải). Dòng 2: tổng tiền (15px,600) + badge (Đã thu/Chưa thu/Thu 1 phần/Ghi nợ/Đã hoàn — màu mẫu chuẩn `.bps--*`). Dòng 3: giờ giao ĐẬM (BỎ icon đồng hồ), đỏ + tag TRỄ khi quá hạn. Dải nút 34px: ← (disabled ở cột Mới nhận) / → / ☰. **Icon = SVG INLINE kiểu Tabler** (arrow-left/right, menu, note) — KHÔNG dùng CDN/webfont như mockup (không hợp PWA offline Sunmi; old Chrome). **Icon ship (đơn giao) BỎ** — chưa có field `is_delivery`/module giao (mockup ghi "làm sau"); thêm khi có module. Popup ghi chú mới (`.note-modal`). Sửa lỗi ĐÈ CHỮ dòng 1 trên thẻ hẹp: bỏ `space-between`, `codegrp flex:0 0 auto` + `cust flex:1 1 auto`/`min-width:0`/ellipsis căn phải. NÂNG đáy lưới thẻ `minmax(120→160px,1fr)` + flex-basis 120→160 (6.10 để 120 cho thẻ RỖNG; nay thẻ có nội dung 16px cần rộng hơn) → cột đông vẫn dàn cột con trên màn rộng, KHÔNG cuộn ngang ở 600/1024/1280, không đè chữ. Backend/test KHÔNG đổi (suite 238). Tự kiểm MOCK API (không đụng prod): 4 biến thể thẻ + popup ghi chú + 3 bề rộng PASS. **CẦN TEST SUNMI**: thẻ + icon SVG trên máy thật.
- [x] Stage 6.15: thẻ Kanban — MẪU CHUẨN CHỐT (FRONTEND-ONLY, theo `the-don-kanban-mau.html` bản chốt; KHÔNG đụng change_status/pay-first). Bố cục **2 DÒNG** + dải nút. Dòng 1: mã đơn (16px) + icon ghi chú (cam, khi có notes → popup) + icon ship (xám, render khi `is_delivery===true` — TODO field/module giao, làm sau) | **NHÃN TIỀN chip màu**: paid → xanh, khác → đỏ. **CHỈ 2 trạng thái** (BỎ badge text 'Đã thu/Chưa thu' + BỎ phân biệt partial/debt trên thẻ — đỏ = chưa thu đủ). Dòng 2: tên khách (ellipsis) | giờ giao. Viền trái 3px: paid xanh / else đỏ. **Màu GIỜ GIAO theo độ gấp (tính FRONTEND từ pickup_at vs now — so 2 mốc TUYỆT ĐỐI nên không lệch UTC; cập nhật theo refresh ~30s, KHÔNG timer riêng):** quá giờ → đỏ; còn ≤30 phút → cam; còn xa → thường; LUÔN đậm; **BỎ tag 'TRỄ' + BỎ icon đồng hồ**. Dải nút 34px: ← (disabled ở Mới nhận) / → / ☰ (icon SVG inline, không CDN). **Màu lấy từ TOKEN CSS** (`--ns-*`), KHÔNG hardcode hex — thêm token `--ns-success-bg/--ns-danger/--ns-danger-bg`. Fit thẻ hẹp: line1 `flex-wrap` + money `margin-left:auto` → màn rộng 1 hàng (tiền dồn phải); thẻ quá hẹp (3 cột <~700px) → nhãn tiền TỰ XUỐNG hàng, KHÔNG đè, KHÔNG cuộn ngang (giữ đáy lưới `minmax(160px)`). Giữ: thanh tổng, đếm cột, 3 cột, menu ☰ (chi tiết/in bill/in liên 2), bấm thân thẻ → chi tiết. Backend/test KHÔNG đổi (suite 238). Tự kiểm MOCK API (không đụng prod): 2 màu tiền + 3 mức giờ (xa/cam/đỏ) + note + ship + ← disabled, wide/narrow KHÔNG cuộn ngang, popup ghi chú OK. **CẦN TEST SUNMI**.
- [x] Stage 6.16: thẻ Kanban tinh chỉnh v3 (FRONTEND-ONLY, theo `the-don-kanban-mau.html` v3; KHÔNG đụng change_status/pay-first/backend/test). (1) **BO TRÒN CẢ 4 GÓC** thẻ (radius 8px, giữ overflow:hidden → viền trái + dải nút bo theo). (2) **DÒNG 1 KHÔNG WRAP**: mã đơn (trái) | nhãn tiền (phải), space-between, không xuống dòng (mã clip-ellipsis CHỈ khi cực hẹp <~700px/3 cột → KHÔNG đè, KHÔNG cuộn ngang; máy thật ≥720px hiện đủ mã). (3) **CHUYỂN icon ghi chú + ship XUỐNG DÒNG 2**, đặt TRƯỚC tên khách: `[ship?][note?] tên (ellipsis) | giờ`; icon `flex:0 0`, tên co → dòng 1 luôn sạch (chỉ mã + tiền). (4) Dải nút THẤP 34→**30px** (mũi tên 19, ☰ 17). ← vẫn disabled ở Mới nhận. (5) **FORMAT GIỜ GIAO rút gọn** (`formatPickupBoard` trong lib/datetime): HÔM NAY (giờ VN) → `HH:MM`; khác ngày → `DD/MM HH:MM` (ngày trước, giờ sau). Màu 3 mức GIỮ nguyên (thường / cam ≤30ph / đỏ quá giờ, luôn đậm) — tính FE so 2 mốc tuyệt đối, "hôm nay" theo giờ VN. (6) Tăng GAP thẻ (6→10px) + box-shadow nhẹ. Màu vẫn từ token `--ns-*`. Build modern+legacy. Backend/test KHÔNG đổi (suite 238). Tự kiểm MOCK API: hôm nay (chỉ giờ) / khác ngày (DD/MM HH:MM) / 3 màu giờ / note ở dòng 2 / ship+note / ← disabled / bo 4 góc / dòng 1 không wrap; wide+narrow KHÔNG cuộn ngang. **CẦN TEST SUNMI**.
- [x] Stage 6.17: thẻ Kanban tinh chỉnh + nút chuyển ĐÚNG 1 CỘT/lần (FE + 1 thay đổi backend NHỎ; KHÔNG đụng pay-first). **(4) Nút → chuyển đúng 1 cột:** trước đây cột gộp washing+drying khiến bấm → chỉ washing→drying (nhìn như đứng yên), phải bấm 2 lần. **BACKEND** `_validate_transition`: NỚI luật — cho NHẢY tiến/lùi TỰ DO trong nhóm xử lý tại tiệm `[created,washing,drying,ready]` trong 1 request (trước chỉ cho lùi; nay washing→ready, created→ready OK). VẪN cấm nhảy RA NGOÀI nhóm (created→delivered/completed → 409), giữ ready→delivered (pay-first), delivered→ready (unpaid), terminal khóa. KHÔNG bỏ trạng thái, KHÔNG migration (giữ tùy biến SaaS). Test `test_forward_jump_within_processing_group_allowed` (washing→ready, created→ready) + sửa `test_status_skip_forward_forbidden` (nay test nhảy NGOÀI nhóm bị cấm). Full suite **239**. **FE**: nhóm cột ở 1 NGUỒN `COLUMNS` (sẵn từ 6.10); nút → `patchStatus` thẳng tới trạng thái ĐẦU cột kế (washing/drying → 'ready' 1 lần); cột cuối "Sẵn sàng" → `deliver()` (pay-first). Nút ← lùi về trạng thái CUỐI cột trước; disabled ở cột Mới nhận (theo index cột, không dùng PREV_STATUS nữa). **(1)** Mã đơn cắt "…ĐẦU" giữ ĐUÔI (`direction:rtl` + ellipsis) — chỉ cắt khi thiếu chỗ; máy rộng hiện đủ. **(2)** Thẻ lẻ KHÔNG giãn hết cột: `max-width:240px` + stretch-cap căn trái → mọi thẻ cùng cỡ dù cột 1 hay nhiều thẻ. **(3)** Giờ giao dùng NHÃN BAO (chip) thay đổi-màu-chữ: còn xa → chữ phụ KHÔNG nhãn; ≤30ph → chip CAM (token `--ns-warn`/`-bg`); quá giờ → chip ĐỎ (token `--ns-danger`/`-bg`). Giữ format hôm-nay/khác-ngày + giờ VN. Build modern+legacy. Tự kiểm MOCK API: mã …đầu / thẻ lẻ cùng cỡ / 3 nhãn giờ / → 1 lần washing→'ready' (PATCH target='ready' PASS); wide+narrow KHÔNG cuộn ngang. **CẦN TEST SUNMI**.
- [x] Stage 6.18: tinh chỉnh thẻ Kanban (4 việc; FE + 1 NỚI backend nhỏ cho undo giao). **(1)** Giảm padding ngang body thẻ 13→10px (chữ thêm chỗ). **(2)** Nhãn giờ cam/đỏ CHỈ cho đơn CHƯA xong (created/washing/drying); đơn 'ready' (Sẵn sàng) → giờ TEXT THƯỜNG màu phụ, KHÔNG nhãn, BẤT KỂ quá giờ (đồ giặt xong, mốc hết nghĩa "gấp") — `timeCls = order_status==='ready' ? '' : timeUrgency()`. **(3)** BỎ tự in bill khi giao: gỡ state `autoPrint` + fetch `/settings/pos` + lời gọi `printBill` trong `finishDeliver` — in bill CHỈ qua menu ☰ "In lại bill". Pay-first giữ nguyên. **(4)** Giao đơn ĐÃ THU: bấm → giao THẲNG (KHÔNG popup) + toast "Đã giao đơn {mã} • Hoàn tác" (5s); bấm Hoàn tác → PATCH delivered→ready. Toast nâng cấp thành `{msg, action:{label,fn}}` + thời lượng tùy chỉnh; thêm `undoDeliver()`. **NỚI BACKEND** (đã chốt với chủ): `_validate_transition` cho `delivered→ready` MỌI payment_status (trước chỉ unpaid) — undo CHỈ đổi trạng thái, KHÔNG đụng `payments` (đơn paid vẫn paid; doanh thu = SUM payments không đổi; đơn paid-ở-ready vốn bình thường qua luồng prepay; cancel-paid-from-ready vốn đã khả thi độc lập). BỎ code `CANNOT_REVERT_PAID_DELIVERY`. Test: đổi `test_revert_delivered_paid_blocked` → `test_revert_delivered_paid_now_allowed` (paid/partial/debt lùi OK, payment_status giữ nguyên). Full suite **239** (1 lần fail là 429 RATE_LIMITED ở /track do chạy test lặp trên IP RFC-5737 — KHÔNG liên quan; clear counter → xanh). Build modern+legacy. Tự kiểm MOCK API: padding gọn / ready-quá-giờ giờ-thường-không-nhãn vs created-quá-giờ-đỏ + washing-sắp-cam / giao đã-thu→thẳng+toast Hoàn tác (PATCH [delivered,ready] PASS) / chưa-thu→popup không PATCH PASS; wide+narrow KHÔNG cuộn ngang. **LƯU Ý DEPLOY: backend đổi (delivered→ready) → cần `docker compose restart app`.** **CẦN TEST SUNMI**.
- [x] Stage 6.19 (Stage B — ĐAI AN TOÀN TẦNG DB): CHẶN CỨNG giao đơn chưa thu ở backend (lớp 2 sau pay-first FE lớp 1). `_validate_transition`: khi `ready→delivered` (transition hợp lệ) mà `payment_status ∈ {unpaid, partial}` → raise **409 `PAYMENT_REQUIRED_BEFORE_DELIVERY`**, RAISE **trước** khi đổi `order_status` (đơn giữ nguyên 'ready', không set delivered nửa vời). paid/debt/refunded → giao OK (debt = ghi nợ có chủ đích). Đặt check TRONG nhánh `_FORWARD` hợp lệ → `created→delivered` vẫn `INVALID_STATUS_TRANSITION` (lỗi cấu trúc, không lẫn mã). ⇒ server KHÔNG BAO GIỜ có đơn delivered khi unpaid/partial, BẤT KỂ caller. **BỎ cờ `requires_payment`** (chọn XÓA HẲN field cho gọn — tránh 2 cơ chế song song): gỡ đoạn set ở `change_status` + field ở `schemas/order.py` (đã cập nhật mọi nơi đọc). **Test (sửa/viết trước):** `test_deliver_unpaid_blocked_409` (unpaid+partial → 409 + đơn VẪN 'ready'), `test_deliver_paid_ok`, `test_deliver_debt_ok`; thêm helper `_advance_to_delivered` (thu đủ trước rồi giao); sửa ~10 test đẩy đơn qua delivered (full_forward / backward_forbidden / completed_is_terminal / revert_* / cancel_after_delivered / put_pickup_lock / board_*) cho THU TIỀN TRƯỚC; BỎ `test_revert_delivered_unpaid_ok` (tình huống delivered+unpaid không còn tồn tại). Full suite **238**. **Frontend `OrderDetail.jsx`** (màn GIAO thứ 2): đổi sang PAY-FIRST như Board — bấm giao đơn unpaid/partial → mở popup thu‑tiền/ghi‑nợ NGAY (chưa PATCH); thu đủ / ghi nợ (reason BẮT BUỘC) xong mới PATCH delivered; bắt **409 PAYMENT_REQUIRED → mở popup** (KHÔNG nuốt lỗi); tái dùng class popup của Board (`.pay-due/.pay-method/.pay-dismiss`). (Cũng vá lỗi cũ: `recordDebt` của OrderDetail trước đây POST debt KHÔNG reason → 422 từ 6.12; nay có ô lý do.) Build modern+legacy. Tự kiểm MOCK API: deliver unpaid/partial→409 + đơn vẫn ready / paid+debt→200 / OrderDetail unpaid→popup (no PATCH) + Thu đủ→payment‑trước‑PATCH (PASS). **LƯU Ý DEPLOY: backend đổi → CẦN `docker compose restart app`.**
- [x] Stage 6.20 (BUGFIX, frontend-only): mất TÊN khách khi tạo đơn KHÔNG có SĐT. **Nguyên nhân:** `OrderNew.jsx` submit bọc TOÀN BỘ xử lý khách trong `if (phone.trim())` → nhập tên mà không SĐT → bỏ qua khối, không tạo customer, không gửi `customer_id`; `OrderCreate` không có field tên rời và `Order.customer_name` là property đọc từ `customers` → tên rớt ngay tại trình duyệt. **Sửa:** tạo/gắn khách khi CÓ SĐT **hoặc** CÓ TÊN — `if (ph) {tìm/tạo theo SĐT như cũ} else if (nm) {POST /customers {full_name: nm} chỉ‑tên, phone trống}` → backend lưu hợp lệ (customers.phone nullable, create_customer không cần phone) → gắn `customer_id`; không nhập gì → khách vãng lai (customer_id NULL → "Khách lẻ"). KHÔNG đụng backend/migration/logic tìm‑khách‑theo‑SĐT. Màn xác nhận + Board/Search/Detail tự hiện ĐÚNG tên (đọc `order.customer_name` từ customer đã gắn). Build modern+legacy. Tự kiểm MOCK API (drive UI thật): (1) chỉ‑tên → POST /customers `{full_name}` KHÔNG phone + order.customer_id set (PASS); (2) SĐT+tên → như cũ (PASS); (3) trống → không tạo customer, customer_id NULL (PASS); (4) tra theo tên → tìm ra (`_apply_search` theo full_name có từ 6.11). Frontend-only → KHÔNG cần restart.
- [x] Stage 6.27 (CHỐT fallback thẻ /board Chrome 56 — frontend-only): 6.26 (radius + inline-block) làm LỖI VIỀN TÁI XUẤT → kết luận **border-radius CŨNG dính bug paint Chrome 56** (không chỉ radius+shadow). Quyết định: **BỎ HẲN border-radius ở fallback** (thẻ VUÔNG GÓC máy cũ) — đúng cấu hình 6.25 đã xác nhận chạy (viền đủ MỌI thẻ) + 2 thẻ/hàng. **(1)** `.board3__card` fallback = `border:1px solid var(--ns-border)` 4 cạnh + `border-left:3px solid` màu (var --paid/--owe) + `background:var(--surface)` + max-width 240. **KHÔNG radius / KHÔNG shadow / KHÔNG overflow.** `border-radius`+`box-shadow` CHỈ ở nhánh `@supports(display:grid)` Chrome mới. **(2)** 2 thẻ/hàng đổi từ inline-block (6.26) → **FLOAT** (an toàn nhất cho viền Chrome cũ): `.board3__cards>*{float:left;width:calc(50% - 5px);margin:0 0 10px}` + `:nth-child(2n){margin-left:10px}` (khe ngang) + `:nth-child(odd){clear:left}` (mỗi hàng mới sạch, tránh float so le khi thẻ cao thấp khác) + clearfix `.board3__cards::after{content:"";display:block;clear:both}`. `@media(max-width:720px)` → 1 thẻ/hàng. **(3)** màu var (Chrome 56 OK). **(4)** nhánh `@supports(grid)` Chrome ≥57: grid auto-fit + reset float:none/width:auto/margin:0 + clearfix `::after{display:none}` (tránh ô grid rỗng) + thẻ radius 8px + box-shadow (GIỮ bản đẹp). Verify soi CSS build (KHÔNG headless): fallback card border+border-left var, KHÔNG radius/shadow/overflow (sanity 0); `.board3__cards>*` float:left+calc; nth-child 2n margin + odd clear; clearfix `:after{content:"";clear:both}` (minifier rút `::after`→`:after`, CSS2 — Chrome 56 OK); @media 1/row; @supports reset float + radius/shadow. CSS hash `index-JibY5KDa.css`. Frontend-only, không restart. **TEST MÁY POS**: 2 thẻ/hàng, thẻ VUÔNG GÓC, viền 4 cạnh đầy đủ + viền trái màu, MỌI thẻ không sót.
- [x] Stage 6.26 (CHỐT fallback thẻ /board Chrome 56, frontend-only — dọn code thí nghiệm 6.25): kết quả 6.25 xác nhận thẻ viền hardcode TỐI THIỂU (không radius/shadow/overflow/var) HIỆN ĐỦ 4 cạnh trên Chrome 56 → thủ phạm là **combo border-radius + box-shadow** (radius đơn lẻ OK, var OK). Hoàn thiện nhánh fallback Chrome<57: **(1) VISUAL thẻ** dùng chung 2 nhánh — `.board3__card` = `border:1px solid var(--ns-border)` 4 cạnh + `border-left:3px solid` màu (var --ns-border-2 / --paid var(--ns-success) / --owe var(--ns-danger)) + `border-radius:8px` + `background:var(--surface)` + `max-width:240px`. **GIỮ radius** (radius-không-shadow chạy OK Chrome 56). **BỎ box-shadow** ở fallback (combo radius+shadow = bug paint). KHÔNG overflow (6.24). `box-shadow` CHỈ thêm ở nhánh `@supports(display:grid)` (Chrome mới). BỎ `display:flex` trên thẻ — con (main/actions) xếp block; display thẻ do `.board3__cards>*` quyết. **(2) 2 THẺ/HÀNG bằng INLINE-BLOCK** (KHÔNG flex-wrap — flex-line Chrome cũ gây bug paint, 6.23): `.board3__cards{display:block}` + `.board3__cards>*{display:inline-block;vertical-align:top;width:calc(50% - 5px);margin:0 0 10px}` + `:nth-child(2n){margin-left:10px}` (khe ngang) → 2 thẻ khít 100% (React .map không chèn whitespace). `@media(max-width:720px)` → 1 thẻ/hàng. **(3)** màu var (chạy tốt Chrome 56): viền trái + nhãn tiền/giờ. **(4)** nhánh `@supports(display:grid)` Chrome ≥57 GIỮ NGUYÊN: grid auto-fit (reset inline-block→block/width auto/margin 0) + box-shadow trên thẻ. Verify soi CSS build (KHÔNG headless): fallback `.board3__card` có var+border+radius, KHÔNG shadow/overflow (sanity 0); `.board3__cards>*` inline-block+calc; @media 1/row; 2 khối @supports(grid). CSS hash `index-CH61ZMxK.css`. Frontend-only, không restart. **TEST MÁY POS**: 2 thẻ/hàng, MỌI thẻ đủ 4 cạnh + bo góc + viền trái màu (không còn mất khung).
- [x] Stage 6.25 (CHẨN ĐOÁN — TẠM, frontend-only): viền thẻ /board Chrome 56 — phương pháp LOẠI TRỪ (6.23 container + 6.24 overflow đều CHƯA hết; USB debug không được vì máy khóa Factory Mode). Rút `.board3__card` ở nhánh fallback Chrome<57 xuống TỐI THIỂU viền THUẦN HARDCODE: `border:1px solid #cccccc` + `border-left:3px solid #cccccc` (paid `#0f6e56` / owe `#a32d2d`) + `background:#ffffff` + `display:flex;flex-direction:column;max-width:240px`. BỎ HẾT: var() (loại trừ var không resolve), `overflow`, `border-radius`, `box-shadow`. Thẻ vuông, viền cứng. Nhánh `@supports(display:grid)` (Chrome ≥57) KHÔI PHỤC đầy đủ (var màu, radius 8px, box-shadow) — ĐẶT SAU rule base để thắng cascade; Chrome 56 không vào nhánh này nên giữ bản hardcode. Mục tiêu: xác định thẻ viền hardcode thuần có hiện đủ 4 cạnh trên Chrome 56 không → khoanh vùng thủ phạm. Build hash CSS `index-CmrFzINI.css`. Verify soi CSS build: fallback card thuần hardcode (0 var/radius/shadow/overflow), @supports khôi phục. **CHỜ KẾT QUẢ MÁY POS** để quyết bước kế (nếu hardcode VẪN mất viền → bug sâu hơn (flex/paint cơ bản); nếu OK → nhả dần var/radius/shadow tìm cái gây vỡ). Frontend-only, không restart.
- [x] Stage 6.24: viền thẻ /board Chrome 56 — LẦN 2 (6.23 đổi container→block VẪN chưa hết). Quan sát máy thật: cột ÍT thẻ OK; cột NHIỀU thẻ → thẻ GIỮA/CUỐI mất khung (01-00010/00012 mất, 00011 còn; 00007/00008 đứt). Container đã `display:block` (6.23) mà vẫn lỗi → gốc bệnh ở CHÍNH THẺ, không phải container. NGUYÊN NHÂN: `.board3__card` có combo `overflow:hidden` + `border-radius:8px` + `box-shadow` → Chrome cũ tạo LỚP CLIP bo góc, thẻ phải REPAINT (cột nhiều thẻ, cuộn/chồng lớp) bị DROP border/shadow (bug paint kinh điển Chrome ~56) → thẻ giữa/cuối mất khung; cột ít thẻ không repaint nên còn. FIX (Cách A, frontend-only, chỉ index.css): **BỎ `overflow:hidden`** trên `.board3__card`. Viền trái là `border-left:3px solid` THẬT (không ::before) nên bỏ overflow KHÔNG mất nó; con (main/actions/nút) đều nền trong suốt nên KHÔNG thò ra góc bo; `border-radius` vẫn bo border thật + background. GIỮ: border 1px 4 cạnh, border-left 3px màu (--paid xanh/--owe đỏ), border-radius 8px, box-shadow, max-width 240px, nhánh grid/block của 6.23. Verify RÀ LOGIC + soi CSS build (KHÔNG headless — Chromium mới không tái hiện bug Chrome 56): `.board3__card` built = `…border:1px…;border-left:3px…;border-radius:8px;box-shadow:…` KHÔNG còn `overflow:hidden`; rule vô điều kiện (ngoài @supports). Cách B (bỏ box-shadow ở Chrome<57) để dành nếu A chưa dứt. Build modern+legacy. KHÔNG restart (FE). KHÔNG test suite (thuần CSS). **TEST MÁY POS**: mọi thẻ (đầu/giữa/cuối, cột ít/nhiều) đủ border 4 cạnh + viền trái màu.
- [x] Stage 6.23: viền thẻ /board VẪN đứt trên Chrome 56 (sau 6.22 đổi 1px) — QUY LUẬT từ ảnh máy thật: **thẻ ĐẦU cột có khung, thẻ giữa/cuối MẤT khung** → KHÔNG phải độ dày border. ĐÃ ĐỌC KỸ: border ở `.board3__card` áp **VÔ ĐIỀU KIỆN** (ngoài mọi @supports/@media, line 2647) cho mọi thẻ ở CẢ 2 nhánh → bác bỏ giả thuyết "viền chỉ ở nhánh grid". box-sizing border-box global. NGUYÊN NHÂN THẬT: container fallback `.board3__cards` (nhánh Chrome <57) dùng combo `display:flex; flex-wrap:wrap; margin:-5px` + con `flex:1 1 160px; margin:5px` + thẻ có `overflow:hidden`+`border-radius`+`box-shadow` → Chrome 56 dính **bug paint flex-line của Chrome cũ**: chỉ item ĐẦU mỗi flex-line vẽ đúng decorations, thẻ sau mất border/shadow (khớp quy luật "đầu có, sau mất"). FIX (frontend-only, chỉ index.css): nhánh fallback đổi sang **BLOCK FLOW** — `.board3__cards{display:block}` + `.board3__cards>*{margin:0 0 10px}` (bỏ flex-wrap + margin âm + flex-basis). Mỗi `.board3__card` thành **block độc lập** → border 4 cạnh LUÔN vẽ đủ, không phụ thuộc vị trí, không dính bug flex. Nhánh `@supports(display:grid)` (Chrome ≥57) GIỮ NGUYÊN (grid auto-fit). KHÔNG hồi quy POS: cột trạng thái ~310px vốn chỉ chứa 1 thẻ/hàng (thẻ ≤240px) nên flex-wrap cũ cũng xếp dọc — block xếp dọc y hệt. Card giữ `display:flex;flex-direction:column` cho layout NỘI BỘ (main+actions, flex 2-item đơn giản, không ảnh hưởng border ngoài). KHÔNG kiểm bằng headless (Chromium mới render khác Chrome 56, không tái hiện bug); verify bằng RÀ LOGIC + soi CSS đã build: fallback `.board3__cards{display:block}` (ngoài @supports), border thẻ vô điều kiện, không còn flex-wrap/margin âm ở fallback, nhánh grid còn nguyên. Build modern+legacy. KHÔNG restart (FE). KHÔNG test suite (thuần CSS). **TEST MÁY POS THẬT**: mở /board, xác nhận MỌI thẻ (đầu/giữa/cuối cột) đều có khung 4 cạnh.
- [x] Stage 6.22: SỬA viền khung thẻ Kanban /board ĐỨT ĐOẠN trên Chrome 56 (POS Sunmi T1-G). NGUYÊN NHÂN: khung thẻ vẽ bằng `border` THẬT 4 cạnh nhưng top/right/bottom = **0.5px** (`.board3__card border: 0.5px solid var(--ns-border)`; cạnh trái 3px màu đè qua `border-left`); box-shadow chỉ là 1 lớp bóng mờ, KHÔNG phải khung. Chrome 56 + màn density thấp làm tròn 0.5px (<1 device-pixel) về 0 KHÔNG đều giữa các cạnh (sub-pixel border, tệ hơn khi kèm border-radius+overflow:hidden) → cạnh trái 3px luôn hiện, 3 cạnh 0.5px rụng tuỳ thẻ → "trên/trái có, dưới/phải mất, góc hở". FIX (frontend-only, chỉ index.css): đổi **0.5px → 1px** cho cả 4 hairline của /board: `.board3__card` border (2650), `.board3__col` border (2597), `.board3__actions` border-top (2742), `.board3__act` border-right (2752). Giữ nguyên `border-left:3px` màu, border-radius 8px + overflow:hidden, box-shadow, màu (var Chrome 56 OK), flex gap (6.21). Verify headless DPR=1 (worst case): 4 cạnh khung = top/right/bottom 1px + left 3px, khung khép kín 4 góc cả thẻ paid (xanh) lẫn owe (đỏ). Build modern+legacy. KHÔNG restart (FE). KHÔNG test suite (thuần CSS). LƯU Ý: còn 8 chỗ `0.5px solid` ở màn KHÁC (app-nav, lien2 modal, board-stats, cashbook…) có thể vỡ tương tự trên Chrome 56 — chưa sửa (ngoài phạm vi stage này, /board).
- [x] Stage 6.21: SỬA flex `gap` không chạy Chrome 56 (máy POS Sunmi T1-G, Android 6 — xác nhận UA `Chrome/56.0.2924.87` trong nginx access.log). flex gap cần Chrome 84+ → trên 56 khoảng cách sụp về 0 (KHÔNG có polyfill, phải sửa tay). FRONTEND-ONLY, chỉ index.css. Rà TOÀN APP: chỉ **4 chỗ** dùng `gap` trên `display:flex` không fallback (toàn app còn lại đã dùng pattern `> * + * {margin}` — ~130 chỗ, Chrome-56-safe sẵn). SỬA cả 4 = bỏ hẳn `gap`, thay `> * + * {margin-left}` (chạy mọi Chrome, không cộng dồn): (1) `.board3__l1` gap 8→`> *+* margin-left:8px` (dòng mã đơn|tiền; có space-between nhưng giữ margin làm SÀN 8px khi mã dài co lại không chạm tiền); (2) `.board3__l2` gap 8→`margin-left:8px` (cụm trái|giờ); (3) `.board3__l2left` gap 6→`margin-left:6px` (icon↔icon↔tên); (4) `.toast` gap 16→`margin-left:16px` (chữ↔nút Hoàn tác — chỗ thứ 4 NGOÀI 3 chỗ board, tìm thêm khi rà toàn app). GIỮ NGUYÊN grid gap `.board3__cards` (2636-2637, đã gate `@supports(display:grid)`, Chrome 56 dùng nhánh flex-wrap fallback) + var()/màu/border-radius (Chrome 56 hỗ trợ đủ, từ Chrome 49). Verify headless (đã bỏ gap → modern Chromium dùng đúng margin như Chrome 56): đo spacing l2=8 / icon-icon=6 / icon-tên=6 / toast=16px; thẻ + chip màu + viền trái render đúng. Build modern+legacy. KHÔNG restart (FE). KHÔNG chạy test suite (thuần CSS, backend không đụng).
- [x] Stage 6.9.11: nhãn liên 2 — giảm 1/2 khe vạch mốc ↔ mã đơn: `.lbl__cutline` margin-bottom 26→13px (đo print-emul xoay: khe mã đơn↔vạch 28→15px, vạch vẫn ngay mép cắt). Thuần CSS.
- [x] Stage 6.9.10: mã đơn VẪN cắt sát (máy trim cả spacer TRẮNG — trắng=trắng với máy nhiệt) + giảm chiều cao nhãn. (1) **VẠCH MỐC CÓ MỰC** thay spacer trắng: `.lbl__cutline` (div, `border-top: 2px solid #000` chỉ khi `@media print`, `margin-bottom: 26px`) đặt ĐẦU DOM trong `.lbl` → khi IN xoay 180° rơi xuống NGAY MÉP GIẤY MÁY CẮT (đáy). Vạch CÓ MỰC → máy KHÔNG trim qua; khe trắng 26px giữa vạch và mã đơn bị "kẹp" giữa 2 phần tử có mực (vạch + mã đơn) → KHÔNG bị trim. Verify print-emul (xoay 180°): vạch cách đáy giấy **0px** (ngay mép cắt), khe **mã đơn → vạch = 28px** (mã đơn cách mép cắt 30px) ✓ trong ngưỡng 24-30px; ghi chú→đỉnh 10px (không dư). Màn hình: cutline height 0 + không border → ẩn, không lệch preview. (2) **GIẢM CHIỀU CAO** (không giảm font): `.lbl__info` line-height 1.6→1.3; `.lbl__head` margin-bottom 14→8; `.lbl__pay` margin-bottom 12→8; `.lbl__note` margin-top 10→6; Time margin-top 4 giữ. Chiều cao nhãn **248→206px** (~42px ngắn hơn). Giữ font (mã 34/trạng thái 18 nowrap/Time 23 center/thân 18), xoay 180°, dữ liệu/mapping, ghi chú weight 400, queue. Full suite 236. **CẦN TEST SUNMI**: mã đơn hết cắt sát (vạch mốc + khe 28px); vạch nằm đúng mép cắt; nhãn ngắn gọn.
- [x] Stage 6.9.9: SỬA DỨT ĐIỂM mã đơn bị cắt sát (nhãn liên 2). Gốc: nhãn xoay 180° khi in → mã đơn (phần tử ĐẦU DOM) rơi xuống ĐÁY giấy = mép máy cắt; TĂNG padding-top nhiều lần KHÔNG hiệu quả (máy in BỎ trailing blank / padding ở mép trang). FIX: thêm phần tử **SPACER có chiều cao THẬT** `.lbl__spacer` (div trắng, `aria-hidden`) đặt ĐẦU DOM trong `.lbl` (trước `.lbl__head`) → khi xoay 180° spacer nằm DƯỚI mã đơn = giữa mã đơn và mép cắt; là content (máy feed hết vùng này rồi mới tới mã đơn), KHÁC padding. Chiều cao CHỈ khi in: `.lbl__spacer{height:0}` + `@media print{.lbl__spacer{height:44px}}` (màn hình=0 → không lệch preview). Đặt `.lbl` padding-top 32→**0** (khe cắt do spacer lo), giữ padding-bottom 10px (phía ghi chú, không dư). VERIFY print-emulation (transform matrix(-1,0,0,-1)=xoay 180°): khe **mã đơn → mép cắt (đáy giấy) = 46px** (≥30px tiêu chí ✓), khe ghi chú→đỉnh giấy = 10px (không dư ✓); screenshot chiều IN xoay khớp. KHÔNG đổi gì khác (font/trạng thái 18px/Time center/ghi chú giữ nguyên 6.9.8). Full suite 236. **CẦN TEST SUNMI**: mã đơn hết cắt sát chưa (spacer 44px); nếu máy VẪN trim cả spacer trắng → bước sau thêm 1 vạch mảnh ở mép spacer làm mốc chống trim (hiện theo yêu cầu giữ spacer trắng không nội dung).
- [x] Stage 6.9.8: tinh chỉnh nhãn liên 2 v7 (CHỈ CSS — Lien2Label.jsx KHÔNG đổi; giữ luồng in/dữ liệu/xoay 180°). (1) **PADDING MÃ ĐƠN — đo bằng PRINT-PREVIEW XOAY 180° (không đoán theo màn hình):** mã đơn là phần tử ĐẦU → `padding-top` LUÔN là khe cạnh mã đơn (dù máy có áp dụng transform hay không). Đo print-emul (transform matrix(-1,0,0,-1)): mã đơn rơi xuống ĐÁY giấy (mép máy cắt), khoảng cách mã→mép = ĐÚNG padding-top; ghi chú rơi lên ĐỈNH giấy (nơi leader gap), khoảng cách = padding-bottom. 6.9.7 để padding-top 22px (đo 24px) VẪN bị máy cắt sát → **TĂNG padding-top 22→32px** (đo lại: khe mã→mép cắt 24→34px). **GIẢM padding-bottom 28→10px** (đo: khe ghi chú→đỉnh 28→10px) để BỎ trắng thừa vùng ghi chú. ⇒ `padding: 32px 6px 10px`. Núm chỉnh khe cắt mã đơn = padding-top (tăng tiếp nếu máy thật vẫn sát). Sửa hiểu nhầm mockup (tưởng padding-bottom mới cạnh mã đơn — sai, là padding-top). (2) Trạng thái TT TO hơn + PAID=UNPAID cùng cỡ (chung rule `.lbl__pay`). Mockup đề 21px nhưng đo print-preview: "CHƯA THANH TOÁN / UNPAID" (24 ký tự) ở 21px TRÀN ~28% khổ 80mm (ước lượng Roboto máy thật hẹp hơn vẫn tràn ~13%) → chọn **18px** (16→18, lớn nhất trong thang 20/19/18 mà vừa 1 dòng theo đo Roboto; nowrap). Knob: tăng 19/20 nếu máy còn rộng, giảm 16 nếu tràn. (3) `.lbl__time` text-align **center** + 22→23px. (4) `.lbl__note` font-weight 700→**400** (chữ thường). (5) `.lbl__head` margin-bottom 12→14px. Font GIỮ sans giống bill (6.9.7). Verify headless: print-emul đo khe mã→mép cắt 34px (không sát) + khe ghi chú→đỉnh 10px (bớt thừa); screenshot chiều đọc + chiều IN (xoay 180°) khớp v7. Full suite 236. **CẦN TEST SUNMI**: mã đơn còn cắt sát không (nếu còn → tăng padding-top); "CHƯA THANH TOÁN / UNPAID" có gọn 1 dòng ở 18px không (nếu tràn → 16px; nếu dư → tăng).
- [x] Stage 6.9.7: tinh chỉnh nhãn liên 2 v6 (CHỈ UI Lien2Label + CSS, không đổi luồng in/dữ liệu/xoay 180°). (1) FONT đổi từ monospace 'Courier New' → GIỐNG BILL `'Segoe UI', system-ui, sans-serif` (.rcp). (2) `.lbl` padding `22px 6px 28px`: top 22px tránh máy cắt SÁT mã đơn (sau xoay 180° mã ở đầu nhãn — ảnh in thật bị sát mép); bottom 28px = vùng nhân viên VIẾT TAY (thay dòng dấu chấm) + hứng leader gap; ngang 6px lề mỏng (nội dung rộng gần hết khổ, bớt trắng 2 bên). (3) Trạng thái TT ÉP 1 DÒNG: `white-space:nowrap` + font 16px (đo headless font fallback rộng: 18/17px TRÀN khổ 80mm, 16px vừa khít; máy thật Roboto hẹp hơn nên dư — nếu vẫn tràn giảm 15px). PAID không khung / UNPAID khung 3px (giữ). (4) BỎ dòng dấu chấm `.lbl__dots` → khoảng trắng padding-bottom làm vùng viết tay. Sizes v6: mã 34, số túi 28, Time 22, info 18, note 17. Giữ nguyên xoay 180° (verify print-emul: transform matrix(-1,0,0,-1) + #root display:none + .print-lien2 block), dữ liệu/mapping/ngày DD/MM, Name+giờ nhận cùng dòng, ghi chú chỉ khi có, queue 1-job-1-bấm. Verify headless: render 2 biến thể khớp mockup v6, trạng thái 1 dòng không tràn. Full suite 236. **CẦN TEST SUNMI**: padding top/bottom/ngang đúng mép cắt + vùng viết tay sau xoay? trạng thái UNPAID có gọn 1 dòng trên máy (Roboto) không (nếu tràn → 15px)?
- [x] Stage 6.9.6: tinh chỉnh mẫu nhãn liên 2 v5 (đậm/rõ hơn, CHỈ UI Lien2Label, không đổi luồng in/dữ liệu/xoay 180°). Font đậm (thân 700, nhấn 800) + to hơn (mã 34px, trạng thái 22px, Time 21px, thân 17px). Trạng thái IN HOA "ĐÃ THANH TOÁN / PAID" (không khung) vs "CHƯA THANH TOÁN / UNPAID" (CÓ khung 3px — cảnh giác khi giao, chủ ý). BỎ viền ngoài nhãn + gạch ngang dưới header. Dòng giao: "Time: DD/MM HH:MM" cùng dòng, to+đậm nhất. Dòng nhận: Name + giờ nhận HH:MM cùng dòng. Dòng ghi tay: dấu chấm "....." (thay gạch liền). padding-bottom 14px giảm giấy trắng đáy (ghi chú: 1 phần là leader gap khi xoay 180° — tinh chỉnh sau test máy). Giữ nguyên xoay 180°, mapping paid→PAID/khác→UNPAID, ngày DD/MM, queue 1-job-1-bấm. Full suite 236.
- [x] Stage 6.9.4: tách bill ↔ liên 2 + từng nhãn thành các PRINT JOB RIÊNG (máy nhiệt Sunmi CHỈ cắt ở CUỐI mỗi window.print(); page-break KHÔNG cắt). Mới `lib/printQueue.js` `usePrintQueue`: hàng đợi in TUẦN TỰ, mỗi mảnh = 1 `window.print()`; chờ job xong bằng `afterprint` HOẶC **fallback timeout `PRINT_FALLBACK_MS=1000ms`** (Sunmi không bắn afterprint đáng tin); token chống double-advance; body class `print-job-bill`/`print-job-lien2` → CHỈ job đang in hiển thị (CSS `@media print`), không in lẫn. AUTO-PRINT (auto_print=TRUE): `runPrint([{mode:'bill'},{mode:'lien2',seq:null}])` → bill rồi 1 nhãn không số, 2 tờ rời; xong → màn tóm tắt (KHÔNG auto về đơn mới — bỏ afterprint→startNew cũ vì xung đột queue). IN CHỦ ĐỘNG (Lien2PrintButton): mỗi nhãn 1 job (1/N→N/N), nút disable khi đang in. BỎ `.print-receipt--label`/page-break nối + `body.print-mode-lien2` + page-break giữa nhãn (không cần). Giữ `@page billpg 80mm×500mm` cho bill (tránh cap 1056px) + rotate 180 nhãn. Verify headless: queue gọi window.print() 3 lần tuần tự KHÔNG cần afterprint (timeout đẩy), body class đúng từng job, onDone 1 lần, dọn class; CSS chỉ job đang in hiện. Toàn flexbox. Full suite 236. **CẦN TEST SUNMI**: bill↔liên 2 cắt rời 2 tờ? in chủ động 2-3 nhãn cắt rời + đúng thứ tự? queue không treo (fallback cứu)? không in chồng/lẫn?
- [x] Stage 6.9.3: sửa bill vắt 2 trang + liên 2 không in. NGUYÊN NHÂN bill "1/2 2/2": `@page { size: 80mm auto }` bị Chromium GIỚI HẠN chiều cao trang ~ khổ mặc định (~Letter 1056px) → bill 2H dài (ghi chú song ngữ + footer) vượt cap → vắt 2 trang (KHÔNG phải do khổ giấy plugin). FIX: thêm `@page billpg { size: 80mm 500mm; margin:0 }` + `.rcp { page: billpg }` → bill ≤500mm nằm trọn 1 trang (đã verify: bill giả lập 1600px > cap vẫn 1 trang). Nhãn liên 2 (ngắn) vẫn dùng `@page auto`. CSS print sạch: không min-height/100vh/page-break trong lòng bill; html/body/#root/.print-receipt height:auto. LIÊN 2: đã xác nhận `<Lien2BillLabel>` LUÔN render cạnh `<Receipt>` (auto-print in cùng tiến trình) — verify trong print-emulation: label display:block, h≈280, là trang 2 (sau bill, qua `page-break-before/break-before` trên `.print-receipt--label` — chỗ ngắt DUY NHẤT). Trước đây user thấy "label absent" do bill vắt 2 trang đẩy label xuống trang 3 (hoặc cache build cũ). CHỈ CSS. **CẦN TEST SUNMI**: máy "80 auto" có cắt bỏ blank đuôi của trang cố định 500mm không (nếu KHÔNG → giảm billpg height); cắt rời bill↔nhãn. Full suite 236.
- [x] Stage 6.9.1: chỉnh nhãn liên 2 + xoay 180° khi in. Nội dung: "Tên/Name"→"Name"; bỏ dòng "Nhận/Receiving time" riêng → Name (trái) + giờ nhận HH:MM (phải) cùng 1 dòng (`formatLabelTime`, KHÔNG ngày); Giờ giao GIỮ dòng riêng to/đậm + đầy đủ "DD/MM HH:MM". XOAY 180° KHI IN: `@media print` `.print-receipt--label .lbl, .print-lien2 .lbl { transform: rotate(180deg); transform-origin:center }` — bố cục giữ nguyên, màn hình không xoay; xoay để leader gap (~1cm đầu tờ) rơi vào vùng dòng kẻ ghi tay (đáy). CHỈ nhãn, không đụng bill. Mapping TT giữ paid→Paid / khác→Unpaid (debt không xuất hiện trên nhãn vì ghi nợ xảy ra SAU khi giao, nhãn đã in trước). **CẦN TEST SUNMI: rotate 180** (plugin có tôn trọng transform? lệch mép? gap đúng vùng?). Full suite 236.
- [x] Stage 6.9: IN LIÊN 2 (nhãn dán túi đồ, nội bộ — khác bill khách). Mẫu CỐ ĐỊNH mọi tenant (không builder), 80mm nhiệt, monospace: mã đơn to góc trái + ô số túi "2/3" đóng khung góc phải (ẩn khi không số) + trạng thái TT đóng khung ("Đã thanh toán / Paid" nếu paid, còn lại "Chưa thanh toán / Unpaid") + Tên (đậm) + Nhận/Receiving (created_at, nhỏ xám) + Giao/Delivery (pickup_at, to đậm) + Ghi chú (CHỈ khi notes≠rỗng) + 1 dòng kẻ trống ghi tay. Ngày dạng "DD/MM HH:MM" (formatLabelDateTime — KHÔNG "Hôm nay/Ngày mai" vì nhãn qua ngày). Component: Lien2Label.jsx (Lien2LabelBody + Lien2BillLabel portal .print-receipt--label) + Lien2PrintButton.jsx (modal chủ động: số nhãn nhanh 1–5 + stepper + checkbox "Đánh số" mặc định tích; in N nhãn rời, page-break giữa nhãn). 2 chế độ: (a) AUTO kèm bill — 1 nhãn KHÔNG SỐ in chung 1 lần với bill (theo auto_print_receipt 6.8.2); (b) CHỦ ĐỘNG — modal, body.print-mode-lien2 ẩn bill chỉ in .print-lien2, KHÔNG phụ thuộc auto_print. Nút "In liên 2" thêm ở màn "Đã tạo đơn" (cạnh In lại/In phiếu). Data lấy từ order response (đủ field, không cần endpoint mới). Toàn flexbox, không emoji. Test: tests/test_lien2_label_data.py (2). **CẦN TEST SUNMI**: in nhiều nhãn liên tiếp + TỰ CẮT giữa các nhãn (page-break), cắt giữa bill↔nhãn, và sự kiện afterprint (nếu không bắn → bấm "Đóng" dọn). Full suite 236 passed.
- [x] Stage 6.8.2: cấu hình auto-print per-tenant + redesign màn "Đã tạo đơn". BE: `tenant_settings.auto_print_receipt` BOOL default TRUE (migration f0a1b2c3d4e5; thêm vào SettingsPublic/Out/Update → GET /settings/pos trả, PUT /settings owner sửa). FE: OrderNew đọc `auto_print_receipt` từ /settings/pos — BẬT (mặc định, 2H) = tạo đơn tự in (giữ luồng 6.8.1) → màn này [In lại]+[Tạo đơn mới] hint "In xong tự về đơn mới"; TẮT = KHÔNG tự in → màn này [In phiếu]+[Tạo đơn mới] hint "Bấm In phiếu nếu khách cần bill". Toggle owner-only ở ReceiptSettings (lưu ngay qua PUT /settings). Màn "Đã tạo đơn" redesign (`.ordok`): card kẻ thẳng 0.5px radius 8px, header ✓ "Đã tạo đơn", mã đơn 26px đậm, bảng tóm tắt (Tên/Giờ giao đậm đen; SĐT/Giờ nhận xám), nút trái đổi label theo chế độ. Dùng chữ trơn "In phiếu"/"In lại" (tránh emoji □ Sunmi). Giữ printedRef/afterprint/giữ-state/config-race-fix 6.8.1. Test: tests/test_auto_print_setting.py (3). (Mockup HTML lần này KHÔNG kèm trong tin nhắn → làm theo spec text.)
- [x] Stage 6.8.1: sửa 2 lỗi auto-print. LỖI 1 (bill in sai mẫu = DEFAULT_RECEIPT placeholder thay vì config 2H): nguyên nhân auto-print render Bill TRƯỚC khi receipt_config (fetch async trong Receipt) kịp load → fallback DEFAULT. Fix: OrderNew NẠP SẴN config trên mount (`getReceiptConfig`, cùng cache/nguồn với In thủ công) + preload logo (`new Image`, timeout 2.5s), truyền `config` prop xuống `Receipt` (Receipt nhận config sẵn → khỏi fetch, render đúng mẫu ngay render đầu); CHẶN `window.print()` tới khi `printReady = receiptConfig!=null && logoReady`. LỖI 2 (màn trung gian "✓ Đã tạo" nháy trước khi in): render Bill portal NGAY + chỉ hiện 1 dòng "Đang in phiếu…" trước; `setPrinted(true)` SAU khi gọi in → nút lưới-an-toàn (In lại/Tạo đơn mới) chỉ hiện SAU in (dưới hộp thoại), không nháy trước. Giữ printedRef (in 1 lần/đơn) + afterprint→startNew. Chỉ frontend. (Verify: bill auto-print = mẫu custom 2H, không placeholder.)
- [x] Stage 6.8: wizard Xác nhận đơn — "Thêm dịch vụ" giữ thông tin + bỏ màn trung gian (in thẳng). (1) Nút "← Thêm dịch vụ" ở footer CẢ 2 bước → đóng modal về màn chọn, GIỮ NGUYÊN mọi state (SĐT/tên/ghi chú/giờ/thu trước-sau/phương thức/phụ thu-giảm/bước); state vốn ở OrderNew (cha). Thêm `confirmActive`: lần đầu mở = reset + áp rule tự áp; "Thêm dịch vụ" = đóng giữ state; mở lại (bấm TẠO ĐƠN ở giỏ) = RESUME (không reset, tổng tính lại theo giỏ có món mới). reset khi submit/startNew. (2) BỎ màn trung gian "ghi mã + In phiếu": tạo đơn xong → `useEffect` auto `window.print()` (1 lần/đơn, `printedRef`) + listener `afterprint`→`startNew` (về đơn mới). Màn còn lại tối giản (✓ đã tạo + mã + In lại/Tạo đơn mới) làm dự phòng nếu máy không bắn afterprint; mã đơn in rõ trên bill (`order_no` → order_code). Giữ nguyên logic tiền/tạo đơn/in. Chỉ frontend.
- [x] Stage 6.7: màn "Xác nhận đơn" → WIZARD 2 BƯỚC (thay modal 1 trang; lý do: bàn phím ảo che/chồng chéo trên máy cảm ứng). `step` state (1|2) + thanh tiến trình dot 1→2 ở header (bước 2: dot1 ✓ done). BƯỚC 1 = Khách & giờ giao (CÓ nhập liệu, ÍT trường → đủ chỗ khi bàn phím bật): 2 cột (trái SĐT inputmode numeric/Tên/Ghi chú · phải Hôm nay/Ngày mai + select giờ/phút mặc định 08:00); nút "Quay lại" / "Tiếp · Thanh toán →" (chặn giờ quá khứ trước khi sang bước 2 — `goStep2`). BƯỚC 2 = Thanh toán (TOÀN NÚT BẤM, không ô text → bàn phím KHÔNG bật): Tạm tính/Tổng cộng + phụ thu/giảm ẩn sau "+ Phụ thu/giảm giá [Thêm]" (`adjOpen`, mở ra tab Giảm giá/Phụ thu) + Thời điểm thu (Thu trước/Thu sau) + Phương thức (Tiền mặt/CK/QR) + "Thu đủ <tổng> khi tạo đơn"; nút "← Quay lại" (về bước 1) / "Tạo & thu · <tổng>". Tiêu đề + thanh nút CỐ ĐỊNH, `.cfm__body` cuộn nội bộ (max-height calc(100vh−20px)), đường kẻ thẳng + radius 4px (modal 6px). GIỮ NGUYÊN logic (SĐT→khách quen, giờ hẹn, phụ thu/giảm %/đ, Thu trước=full 6.6.4/Thu sau, phương thức, tạo đơn, in bill). Chỉ frontend.
- [x] Stage 6.6.5: sửa nốt modal Xác nhận đơn (CSS/mặc định, KHÔNG đụng logic tiền). (1) Bàn phím cảm ứng Sunmi che modal → overlay confirm dùng `modal-overlay--top` (căn TRÊN thay vì giữa) + overlay cuộn được; `.cfm` max-height theo viewport (`calc(100vh-20px)`), `.cfm__cols` cuộn nội bộ tới ô focus, tiêu đề + thanh nút CỐ ĐỊNH → bàn phím không làm vỡ/chồng chéo (đã test viewport thấp: title + actions vẫn hiện, giữa cuộn). (2) Giờ hẹn MẶC ĐỊNH 08:00 (hôm nay nếu còn tương lai, không thì ngày mai — luôn hợp lệ) thay vì now+turnaround; select giờ=08 phút=00. (3) Nút đáy radius 4px, cân đối: "Quay lại" 38% + "Tạo & thu" 62% (~38px cao). Chỉ frontend.
- [x] Stage 6.6.4: BỎ thu một phần (lỗi tiền) — 2H chỉ "Thu trước" (đủ 100%) hoặc "Thu sau" (chưa thu). BỎ ô "Số tiền thu" trong modal xác nhận (thay bằng dòng "Thu đủ <tổng> khi tạo đơn"). POST /orders nhận `prepay: bool` + `payment_method` → `order_service.create_order` tự ghi payment = ĐÚNG `total_amount` (server tính, KHÔNG nhận số tiền từ client → không thể thu một phần/sai sổ); prepay kiểm ca mở TRƯỚC (409 NO_OPEN_SHIFT, không tạo đơn mồ côi). Frontend gửi prepay flag thay vì POST /payments số tùy ý. Sổ quỹ/đối soát ca (total_collected, cash_in_drawer) + payment_logs + bill đều khớp full total. Test: tests/test_prepay_full.py (5) — full 270k, full sau giảm 300k−30k=270k + đúng method, thu sau ghi 0, prepay no-shift 409 không tạo đơn, field amount rác bị bỏ qua. Full suite 231 passed.
- [x] Stage 6.6.3: thiết kế lại modal "Xác nhận đơn" (`.cfm`) — 2 cột màn POS ngang, sửa vỡ layout. TRÁI: SĐT/Tên/Ghi chú + [tab Giảm giá | Phụ thu] (gộp 2 tab, mặc định Giảm giá, state độc lập — `adjTab`); PHẢI: Giờ hẹn giao + Tạm tính/Tổng cộng + Thanh toán. **BỎ WheelTimePicker** (wheel tràn/lộn xộn) → dropdown native: nút Hôm nay/Ngày mai + `<input date>` + `<select>` giờ (0-23) + `<select>` phút (QUARTERS) + dòng "Giao lúc:…" (dùng helpers datetime: combineVn/getVnHour/nearestQuarterIndex…; WheelTimePicker.jsx còn lại nhưng KHÔNG dùng). Đường kẻ THẲNG phân vùng (dọc giữa 2 cột, ngang giữa nhóm), radius 4px input/nút/select + modal 6px (override pill→4px), input gọn 34px/font13/nhãn 11px, nút thanh toán mảnh 30px/font12, tổng tiền bỏ khung. Tiêu đề + thanh nút CỐ ĐỊNH (flex none) → TẠO ĐƠN không bị che; "Quay lại" nhỏ trái + "Tạo & thu" chiếm phần còn lại (38px). Giữ nguyên logic (phụ thu/giảm %/đ, giờ hẹn, thu trước/sau, phương thức). Verify @1280×800: modal 720×~490, vừa khung, không cuộn/chồng chéo.
- [x] Stage 6.6.2: tinh chỉnh layout Tạo đơn — đường kẻ thẳng thay bo tròn + card cao đều. Phân vùng 3 cột bằng BORDER thẳng (`.zones__tabs` border-right, `.zones__cart` border-left; bỏ khe margin), bỏ bo tròn vùng/khối lớn (zones__cart bỏ border+radius+shadow; cat-tab & cart__item phân cách bằng border-bottom, radius 0); giữ radius nhỏ 4px ở card dịch vụ + nút + dropdown. Card dịch vụ `height:64px` CỐ ĐỊNH + box-sizing border-box + overflow hidden + `flex:0 0 188px` + `align-content:flex-start` → mọi card cao bằng nhau, không lệch hàng (tên dài clamp 2 dòng trong khung). Cột danh mục 78px: icon = MONOGRAM chữ cái đầu (badge 26px bo 4px) thay emoji — ổn định Chrome cũ Sunmi (emoji hiện □); nhãn 10px wrap 2 dòng căn giữa. Giỏ: mỗi món border-bottom, đáy Tổng+TẠO ĐƠN có border-top. CHỈ CSS + 1 đổi nhỏ JSX (emoji→monogram trong OrderNew). Verify: card đều 64px, không cuộn @1280×800. (Lưu ý: emoji trong menu ☰ vẫn còn — đổi sau nếu cần.)
- [x] Stage 6.6.1: sửa layout Tạo đơn khớp thiết kế + chuyển bộ chọn CN lên header. Bộ chọn chi nhánh (trước là 1 hàng riêng trong OrderNew) → context `BranchContext` (branchId/setBranchId/branches; chủ load + auto-chọn nếu 1 CN; NV cố định theo branch tài khoản); header: CHỦ + màn /orders/new = `<select>` dropdown chọn CN, còn lại = nhãn tên CN. OrderNew dùng branchId từ context (logic giữ nguyên: needbranch, query shift, body.branch_id). Card dịch vụ `flex: 0 0 190px` (CỐ ĐỊNH, không giãn, wrap căn trái, để trống bên phải), min-height 76px (cao hơn, cân đối); giỏ phải 270px + font nhỏ (tên/giá 13px, qty-btn 30px); nhãn danh mục wrap 2 dòng căn giữa (10px, không tràn cột 84px). Verify: card đều 190, cart 270, không cuộn toàn trang @1280×800. Chỉ CSS + chuyển vị trí (JSX: BranchContext + App + Layout + OrderNew), không đổi logic tạo đơn.
- [x] Stage 6.6: tối ưu layout máy POS Sunmi (màn ngang ~1280×800, không cuộn toàn trang) — CHỈ CSS/layout. Header GỌN 1 dòng (bỏ logo/tên tiệm/role/nút Đăng xuất to): `.app-nav` = tab trái + spacer + chip chi nhánh + ☰; tài khoản + Đăng xuất chuyển vào dropdown ☰ (`.app-menu__head`/`.app-menu__logout`). Bỏ hẳn `.app-header`. Màn Tạo đơn: cột danh mục trái 84px (icon+chữ nhỏ), giữa lưới card `flex 1 1 200px` (tự co), card GỌN — tên 1–2 dòng + đơn vị/giá CÙNG 1 hàng (`.svc-card__meta`), ô tìm 1 dòng mảnh dưới lưới; giỏ phải 210px, mỗi món 2 hàng, list cuộn riêng (`flex:1;overflow`), đáy cố định Tổng (gọn) + nút TẠO ĐƠN cùng hàng (bỏ btn--block). `.ordernew--zones height: calc(100vh - 92px)`. Flexbox (không grid/gap — xem 6.5). Verify: nav 50px, không cuộn toàn trang ở 1280×800, nav không tràn 360–1280.
- [x] Stage 6.5: tương thích Chrome cũ máy POS Sunmi (Android 6) — thêm autoprefixer (PostCSS) + browserslist (Android>=6, Chrome>=44); chuyển TOÀN BỘ CSS Grid → flexbox (16 layout, gồm 3 vùng Tạo đơn) + flex `gap` → margin (mẫu `> * + *`) vì Chrome<84 không hỗ trợ gap trong flex; bỏ `:has()` (giữ 1 chỗ progressive) + `inset:` → longhand. Chỉ CSS + build tooling.
- [x] Stage 6.4: tương thích máy POS Android 6 — @vitejs/plugin-legacy (build ES5 + bundle nomodule + polyfills, sửa màn trắng Chrome cũ) + bill in 1 TRANG (ẩn `#root` khi @media print, `@page size:80mm auto;margin:0` — bỏ trang trắng đầu trên Sunmi Printer) + SSL ZeroSSL cho pos.giatui2h.com (gốc USERTrust RSA, Android 6 tin được; thay Let's Encrypt/ISRG).
- [x] Stage 6.3: báo cáo cho chủ (owner dashboard cơ bản) — GET /reports/owner-summary (owner; from_date/to_date/branch_id) trả 4 nhóm: doanh thu (total/by_day/by_branch, đơn TẠO trong khoảng, loại cancelled), nộp chủ (reuse owner_handover_report), lệch két (chỉ liệt kê ca cash_difference≠0 cảnh báo thất thoát, đếm ca khớp), nợ chưa thu (đơn tạo trong khoảng còn nợ = total−SUM(payments)) + màn "📊 Báo cáo" (☰, owner): chọn khoảng ngày (mặc định 7 ngày) + chi nhánh (Tất cả/từng CN) + 4 thẻ số (Doanh thu/Đã nộp chủ/Lệch két đỏ nếu có/Nợ chưa thu) + bảng doanh thu theo ngày & theo CN + danh sách lệch két (highlight) hoặc "Tất cả ca khớp ✓" + danh sách nộp chủ + nợ tổng/số đơn. Bản cơ bản: không biểu đồ/Excel/so sánh kỳ. Read-only, không migration. Test: tests/test_owner_summary.py (7).
- [x] Stage 6.2: đóng ca rút tiền nộp chủ (handover_to_owner; cash_left_for_next=actual−handover, KHÔNG vào expected; 422 nếu vượt) + gợi ý đầu ca = tiền để lại ca trước (GET /shifts/opening-suggestion) + báo cáo nộp chủ (GET /reports/owner-handover) + form đóng ca có ô rút nộp chủ & tiền để lại realtime + 2 phiếu in 80mm (biên nhận nộp chủ + biên bản giao ca với đối soát/bàn giao). Migration e9f0a1b2c3d4.
- [x] Stage 6.1: màn Ca hiện chỉ số realtime — GET /shifts/{id}/summary (cash_in_drawer dùng công thức reconciliation; transfer_total; total_collected theo ca THU; shift_revenue theo ca TẠO đơn; order_count) + màn Ca nhóm "Tiền trong ca" (két nổi bật/CK-QR/tổng thu) & "Doanh thu" (doanh thu ca/số đơn) + nút làm mới. Phân biệt total_collected vs shift_revenue (đơn nợ qua ca).
- [ ] Stage 5: rollout 3 branch + Admin Dashboard + QR tracking công khai
- [ ] Stage 6: Delivery module + COD reconciliation + cron (backup/healthcheck/ssl)
- [ ] Stage 7+: Public API, subscriptions — chỉ khi có khách ngoài thật
