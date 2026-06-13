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
  total_amount NUMERIC(14,0), payment_status, order_status,
  pickup_at timestamptz NOT NULL (giờ hẹn giao, Stage 3.7A, migration c3a1f9d2b7e4),
  notes, created_by FK users, created_at, updated_at
- pickup_at: BẮT BUỘC khi tạo đơn, service validate phải > now (422
  PICKUP_AT_IN_PAST). PUT sửa được khi đơn chưa completed/cancelled (409
  ORDER_CLOSED nếu đã đóng). Đơn cũ migration backfill = created_at + 4h.
- payment_status: unpaid | partial | paid | refunded | debt
- order_status: created | washing | drying | ready | delivered | completed | cancelled
- Unique: (tenant_id, order_code)
- Index: (tenant_id, branch_id, created_at), (tenant_id, order_status), (customer_id)

### order_items
- id UUID PK, order_id FK, service_id FK nullable (→ services), service_name,
  quantity NUMERIC(8,2), unit_price NUMERIC(14,0), subtotal NUMERIC(14,0), created_at
- `service_id` để truy nguồn dòng giá; `service_name`/`unit_price`/`subtotal` là
  SNAPSHOT lúc tạo đơn — sửa bảng giá sau KHÔNG đổi giá đơn cũ.
- Index: (order_id)

### services (Stage 3.5A, migration 8824c0db78cf) — bảng giá động
- id UUID PK, tenant_id FK, name, unit (kg|cai|con|bo|luot), unit_price NUMERIC(14,0),
  pricing_type (per_unit|tier), display_order INT, is_active bool, created_at, updated_at
- category String(64) nullable + is_favorite bool (Stage 3.8, migration e2f3a4b5c6d7):
  gom tab màn tạo đơn; "Hay chọn" = is_favorite=true. owner đánh dấu ở màn bảng giá.
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
  created_at, updated_at.
- Cấu hình per-tenant; chứa secret (bot token) nên tách khỏi bảng `tenants`.
- Đóng ca xong gửi Telegram cho owner (httpx async, SAU commit); lỗi gửi KHÔNG
  làm fail đóng ca. |cash_difference| > cash_diff_threshold → thêm ⚠️ LỆCH KÉT.
- Endpoints (Stage 3.8): GET /settings/pos (mọi role, chỉ field POS — turnaround,
  KHÔNG lộ secret), GET /settings (owner/manager, đầy đủ), PUT /settings (owner).
  Row settings tạo LAZY khi đọc lần đầu (server_default lo giá trị mặc định).
- default_turnaround_hours: POS gợi ý giờ hẹn giao = now(VN) + giá trị này.

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
  `order_code` PHẢI dùng đúng tên này.

## ROADMAP HIỆN TẠI

- [x] Stage 1: skeleton + migration baseline + auth (login/refresh/logout/me) + CRUD tenants/branches/users
- [x] Stage 2: shifts (open/close + reconciliation) + orders + payments + Telegram alert đóng ca
- [x] Stage 3: POS PWA (login, mở/đóng ca, tạo đơn, thu tiền, đổi trạng thái)
- [x] Stage 3.5A: bảng giá dịch vụ động (services + service_tiers) + CRUD + snapshot giá vào order_items
- [x] Stage 3.7A (backend): orders.pickup_at (giờ hẹn giao) + GET /orders/board (dashboard vận hành) + cờ requires_payment khi giao đơn còn nợ
- [x] Stage 3.7B (frontend): wheel time picker + tab Bảng đơn (Kanban) + luồng giao-thanh-toán (modal requires_payment)
- [x] Stage 3.8: thiết kế lại màn tạo đơn 3 vùng không cuộn + tab danh mục/Hay chọn + fix pickup_at múi giờ VN + tenant_settings.default_turnaround_hours + GET/PUT /settings
- [ ] Stage 4: pilot 1 branch Giặt Ủi 2H (chạy song song sổ tay 2 tuần)
- [ ] Stage 5: rollout 3 branch + Admin Dashboard + QR tracking công khai
- [ ] Stage 6: Delivery module + COD reconciliation + cron (backup/healthcheck/ssl)
- [ ] Stage 7+: Public API, subscriptions — chỉ khi có khách ngoài thật
