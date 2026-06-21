# Kế hoạch: Ẩn/Hiện dịch vụ theo chi nhánh (branch service visibility)

> Trạng thái: **THIẾT KẾ — chưa code, chưa áp prod.** Để TRUNG HIEU review.
> Nguyên tắc: mặc định MỌI dịch vụ hiện ở MỌI CN (giữ hành vi cũ); owner chỉ *tắt* (ẩn)
> dịch vụ ở CN cụ thể. **Giá CHUNG** (không custom giá per-CN — owner tạo nhiều dịch vụ
> giá khác nhau rồi ẩn/hiện theo CN).

## 1. Model — bảng mới `branch_hidden_services`

Mỗi dòng = MỘT dịch vụ bị ẩn ở MỘT chi nhánh. **Bảng rỗng = không ẩn gì = hành vi cũ.**

```python
# app/models/branch_hidden_services.py (MỚI) + đăng ký trong app/models/__init__.py
class BranchHiddenService(TimestampMixin, Base):
    __tablename__ = "branch_hidden_services"
    id: uuid_pk()
    tenant_id:  FK("tenants.id")   NOT NULL   # DENORMALIZE — để RLS strict (xem #RLS)
    branch_id:  FK("branches.id")  NOT NULL
    service_id: FK("services.id")  NOT NULL
    __table_args__ = (
        UniqueConstraint("branch_id", "service_id", name="uq_branch_hidden_service"),
        Index("ix_branch_hidden_tenant_branch", "tenant_id", "branch_id"),
    )
```

### RLS cho bảng mới — STRICT theo `tenant_id` (KHÔNG dùng EXISTS-qua-parent)
- Thêm cột `tenant_id` trực tiếp (denormalize, set lúc insert = actor.tenant_id) → policy
  **strict** giống 14 bảng kia: `tenant_id = NULLIF(current_setting('app.current_tenant_id',true),'')::uuid`.
- Lý do KHÔNG dùng EXISTS-qua-parent (như order_items): 3 bảng con kia KHÔNG có tenant_id;
  bảng này ta tự thêm được → strict đơn giản + nhanh + nhất quán. Denormalize rẻ (1 cột uuid).
- ⚠️ **BẮT BUỘC bật RLS + policy cho bảng mới.** Nếu tạo bảng mà KHÔNG enable RLS → `laundry_app`
  (non-owner) thấy MỌI dòng mọi tenant (bảng có GRANT nhưng không policy = không lọc) → leak.

## 2. Migration (mới, nối sau head hiện tại `f6a7b8c9d0e1`)

```python
def upgrade():
    op.create_table("branch_hidden_services", ...)   # cột + uq + index như trên
    op.execute("ALTER TABLE branch_hidden_services ENABLE ROW LEVEL SECURITY")
    op.execute("CREATE POLICY tenant_isolation ON branch_hidden_services "
               "USING (tenant_id = NULLIF(current_setting('app.current_tenant_id',true),'')::uuid) "
               "WITH CHECK (tenant_id = NULLIF(current_setting('app.current_tenant_id',true),'')::uuid)")
    # GRANT: tự động cho laundry_app qua ALTER DEFAULT PRIVILEGES FOR ROLE laundry (R1)
    #   vì bảng do owner `laundry` tạo trong migration. (Có thể thêm GRANT guarded cho chắc.)
def downgrade():
    op.execute("DROP POLICY IF EXISTS tenant_isolation ON branch_hidden_services")
    op.drop_table("branch_hidden_services")
```
- **Backfill: KHÔNG cần** (bảng rỗng = hành vi cũ).

## 3. Lọc khi TẠO ĐƠN (mấu chốt)

`service_service.list_services` ([service_service.py:31](app/services/service_service.py)) thêm param:
```python
async def list_services(db, tenant_id, page, *, include_inactive=False, visible_in_branch=None):
    base = select(Service).where(Service.tenant_id == tenant_id)
    if not include_inactive: base = base.where(Service.is_active.is_(True))
    if visible_in_branch is not None:                       # CHỈ lọc khi có branch
        hidden = select(BranchHiddenService.service_id).where(
            BranchHiddenService.branch_id == visible_in_branch)
        base = base.where(Service.id.not_in(hidden))         # trừ dịch vụ ẩn ở CN đó
    ...
```
`GET /services` ([services.py:19](app/api/v1/services.py)) thêm `branch_id: uuid | None = Query(None)`
→ truyền `visible_in_branch=branch_id`. **Không truyền branch_id → trả HẾT** (màn quản lý/báo cáo).

**OrderNew** ([OrderNew.jsx:110](pos-pwa/src/pages/OrderNew.jsx)) — branch hiệu lực:
- owner → `branchId` (useBranch, header dropdown); staff/manager → `user.branch_id`.
- `const effBranch = isOwner ? branchId : user?.branch_id`
- Load `/services?limit=200${effBranch ? '&branch_id='+effBranch : ''}`, **reload khi effBranch đổi**
  (thêm `effBranch` vào deps useEffect). owner chưa chọn CN (Tất cả CN) → không gửi branch_id
  → thấy hết (nhưng OrderNew vốn chặn tạo đơn khi owner chưa chọn CN — 'needbranch').

**Đơn cũ KHÔNG ảnh hưởng:** order_items **snapshot** `service_name + unit_price + subtotal` lúc tạo
([pricing.py](app/services/pricing.py)) → ẩn dịch vụ chỉ ảnh hưởng tạo đơn MỚI; đơn cũ/bill giữ nguyên. ✅

**An toàn lọc:** subquery `branch_hidden_services` tự RLS-scope theo tenant (GUC). Nếu owner lỡ truyền
branch_id của tenant khác → bảng hidden trả rỗng (RLS) → không ẩn gì (show all) → KHÔNG leak.
*(Quyết định: lọc là DISPLAY-only. order_service.create_order KHÔNG chặn nếu lỡ gửi service ẩn —
tránh vỡ edge case; ẩn = dọn màn, không phải cấm. Nếu muốn cấm cứng thì thêm validate sau.)*

## 4. Chỗ khác load services
- **CHỈ màn TẠO ĐƠN lọc hidden.** Quản lý dịch vụ (ServicesManage), báo cáo → **thấy hết** (không
  truyền branch_id). Lý do: owner quản lý/đối soát cần thấy toàn bộ; ẩn chỉ để gọn màn bán hàng.

## 5. API quản lý ẩn/hiện (owner-only)
Sub-resource dưới branch (gọn, REST rõ):
- `GET  /branches/{branch_id}/hidden-services` → `{ hidden_service_ids: [uuid, ...] }`
- `PUT  /branches/{branch_id}/hidden-services/{service_id}`  body `{ hidden: bool }`
  - `hidden:true` → upsert dòng (ẩn; idempotent, ON CONFLICT DO NOTHING)
  - `hidden:false` → xóa dòng (hiện)
  - trả 200 `{success:true}` (hoặc trạng thái mới).
- Quyền: `require_role("owner")`. Service mới `branch_visibility_service` (set tenant_id=actor.tenant_id
  khi insert; validate branch + service thuộc tenant — RLS cũng chặn sẵn).

FE màn quản lý: GET danh sách services (active) + GET hidden_service_ids → render toggle; toggle → PUT.

## 6. UI — màn "Dịch vụ theo chi nhánh"
- `pos-pwa/src/pages/BranchServiceVisibility.jsx` (MỚI). Dropdown chọn CN (branches active) →
  list dịch vụ + toggle **Hiện/Ẩn** (mặc định Hiện = không nằm trong hidden set). Toggle → PUT.
- Route `/services/visibility`; mục menu ☰ "Dịch vụ theo CN" (icon ví dụ `eye`), `roles:['owner']`,
  đặt cạnh "Bảng giá". CHUẨN STYLE UI (.services/.cat-manage hoặc .shift__card + .modal nếu cần).

## 7. Phạm vi & rủi ro — **VỪA** (không backfill, không đổi model cũ)
**File đụng (~9–11):**
- BE: models/branch_hidden_services.py (mới) + models/__init__.py · migration (mới) ·
  service_service.list_services · api/v1/services.py (param branch_id) · branch_visibility_service (mới) ·
  api/v1/branches.py *hoặc* router mới (2 endpoint) · schemas (visibility).
- FE: OrderNew.jsx (param + reload) · BranchServiceVisibility.jsx (mới) · App.jsx (route) ·
  Layout.jsx (menu + icon) · api.js (helper, tùy).
- Test: lọc tạo đơn theo branch (services trừ hidden) · RLS isolation bảng mới (tenant A không thấy
  hidden của B) · endpoints quản lý · đơn cũ không đổi (snapshot).

**Rủi ro:**
1. ⚠️ **Quên enable RLS + policy bảng mới** → leak cross-tenant (laundry_app thấy hết). Bắt buộc trong migration.
2. **Lọc tạo đơn sai → mất dịch vụ:** chỉ lọc khi có branch_id; mặc định show-all; test kỹ (ẩn 1 dịch
   vụ ở CN1 → CN1 không thấy, CN2 vẫn thấy, không branch → thấy hết).
3. Đơn cũ: an toàn nhờ snapshot (đã xác nhận).
4. order_service không chặn service ẩn (display-only) — chấp nhận; nêu rõ.

**Test-first** (đụng luồng tạo đơn + RLS): viết test trước cho list_services(visible_in_branch) +
RLS isolation bảng mới + 2 endpoint quản lý.
