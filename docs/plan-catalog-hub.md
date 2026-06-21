# Kế hoạch: GOM 4 màn quản lý dịch vụ vào 1 (tab) — chỉ FRONTEND

> Trạng thái: **THIẾT KẾ — chưa code.** Gom: Danh mục · Bảng giá/Dịch vụ · Phụ thu & Giảm giá ·
> Hiển thị theo CN → 1 mục menu + tab bên trong. **GIỮ NGUYÊN logic/CRUD/API/RLS từng màn.**

## 1. Hiện trạng (4 màn)
| Tab | Component | Route cũ | Quyền |
|---|---|---|---|
| Danh mục | CategoriesManage.jsx | /categories | owner+manager |
| Bảng giá / Dịch vụ | ServicesManage.jsx | /services | owner+manager |
| Phụ thu & Giảm giá | PriceRulesManage.jsx | /price-rules | owner |
| Hiển thị theo CN | BranchServiceVisibility.jsx | /services/visibility | owner |

- Cả 4 cùng vỏ `<div className="services"><div className="services__head"><h2 className="services__title">…</h2> + nút/dropdown</div>`.
- Mỗi màn **tự load data** qua API (categories/services/price-rules/branches) — **KHÔNG phụ thuộc component nhau**.

## 2. Phụ thuộc giữa 4 màn
- **Chỉ 1 liên kết mềm:** ServicesManage load `/categories` cho ô chọn danh mục ([ServicesManage.jsx:57](pos-pwa/src/pages/ServicesManage.jsx)) +
  có `<Link to="/categories">` "Quản lý danh mục" ([:217](pos-pwa/src/pages/ServicesManage.jsx)). Đây là API-read + 1 link điều hướng, KHÔNG phải phụ thuộc component.
- 3 màn còn lại độc lập hoàn toàn. → Gom = thuần vỏ (routing + tab), không đụng dữ liệu.

## 3. Cơ chế tab — TỰ LÀM (tái dùng class sẵn, không có component Tab)
- KHÔNG có component Tab dùng chung. Có sẵn class: `.seg`/`.seg__btn` (segmented control, [index.css:1916](pos-pwa/src/index.css)),
  `.app-nav__tab` (nav trên), `.cat-tab` (tab dọc OrderNew).
- **Đề xuất: dùng `.seg`/`.seg__btn`** cho thanh tab (đã styled chuẩn: token, font-weight 500, active state) —
  hợp "chọn 1 trong N". Không cần CSS mới (hoặc thêm 1-2 dòng nếu muốn full-width).

## 4. Cấu trúc gom đề xuất
**Màn cha mới `pos-pwa/src/pages/Catalog.jsx`** (route `/catalog`):
```
const TABS = [
  { key:'categories', label:'Danh mục',          roles:['owner','manager'], C: CategoriesManage },
  { key:'services',   label:'Dịch vụ & bảng giá', roles:['owner','manager'], C: ServicesManage },
  { key:'price-rules',label:'Phụ thu & giảm giá', roles:['owner'],           C: PriceRulesManage },
  { key:'visibility', label:'Hiển thị theo CN',   roles:['owner'],           C: BranchServiceVisibility },
]
// lọc theo user.role → tabs hiển thị (manager: 2 tab; owner: 4)
// tab hiện tại = ?tab= (query param) — deep-link + giữ khi refresh; mặc định tab đầu được phép.
// render: <thanh .seg các tab cho phép> + <ActiveChild />
```
- **Route: 1 route `/catalog` + query param `?tab=<key>`** (deep-linkable, đơn giản; cross-link Services→Danh mục
  dùng `navigate('/catalog?tab=categories')`). Tab không hợp quyền (manager mở ?tab=price-rules) → fallback tab đầu cho phép.
- **Route cũ → redirect** sang `/catalog?tab=…` (giữ bookmark/link cũ không vỡ):
  /services→?tab=services, /categories→?tab=categories, /price-rules→?tab=price-rules, /services/visibility→?tab=visibility.

## 5. Giữ component con — chỉnh NHẸ
- **Giữ nguyên 100% logic** (state, CRUD, API, RLS, guard role) của 4 component.
- Chỉnh duy nhất: **bỏ `<h2 className="services__title">` trùng** (tab đã là tiêu đề) — giữ nút/dropdown trong head.
  (Hoặc giữ title luôn nếu muốn 0 đụng con — chấp nhận title đôi. Khuyến nghị bỏ cho gọn.)
- ServicesManage: đổi `<Link to="/categories">` → `to="/catalog?tab=categories"` (ở-trong-hub).
- ⚠️ Không refactor sâu — chỉ bỏ title + sửa 1 link.

## 6. KHÔNG đụng backend
Gom thuần FE (routing + tab + menu). **BE/CRUD/API/RLS giữ nguyên.** Không migration/restart — chỉ build FE.

## 7. Phạm vi file — VỪA (≈7 file)
- **Mới (1):** `pages/Catalog.jsx` (hub + tab).
- **Sửa nhẹ (4 con):** Categories/Services/PriceRules/BranchServiceVisibility — bỏ h2 title (+ Services sửa 1 link).
- **App.jsx:** thêm route `/catalog`; đổi 4 route cũ thành redirect `/catalog?tab=…`.
- **Layout.jsx:** GỘP 4 mục menu → 1 mục "Dịch vụ & bảng giá" (icon `services`, roles owner+manager) → `/catalog`.
  (Bỏ 4 mục: Bảng giá, Dịch vụ theo CN, Danh mục, Phụ thu/Giảm giá.)

## Rủi ro
- Nhẹ. Chính: (1) tab theo role — manager chỉ thấy 2 tab (lọc đúng + fallback); (2) cross-link Services→Danh mục
  phải chuyển tab thay vì điều hướng ra ngoài; (3) redirect route cũ để không vỡ link. Không đụng dữ liệu → không rủi ro logic.
- Mỗi lần đổi tab → child remount + refetch (chấp nhận; đơn giản). Muốn giữ state thì keep-mounted (phức tạp hơn, không cần).
