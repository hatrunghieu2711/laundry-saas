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
