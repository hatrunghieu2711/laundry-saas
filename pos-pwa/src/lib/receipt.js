// Cấu hình mẫu phiếu in — BILL BUILDER THEO KHỐI (Stage 5.6 → 5.8).
// receipt_config = { bilingual, logo_url, blocks[] }. Owner tự thêm/bớt/sắp xếp/ghép
// khối, sửa nhãn + định dạng (bold/align/size), bật/tắt tiếng Anh.
// Stage 5.8: Tên/ĐT tách riêng; bỏ note/footer_contact/surcharge_discount (dùng
// "Văn bản tự do"); bỏ kẻ ngang tự động; bold tách nhãn vs giá trị cho khối field.
import { api } from './api'

// Khối có NHÃN + GIÁ TRỊ → dùng bold_label / bold_value RIÊNG.
export const FIELD_TYPES = ['customer_name', 'customer_phone', 'receiving_time', 'delivery_time', 'order_no']
export const isField = (type) => FIELD_TYPES.includes(type)

// Metadata mỗi loại khối: nhãn quản lý + căn lề mặc định khi render.
export const BLOCK_META = {
  logo:           { label: 'Logo (ảnh)', align: 'center' },
  customer_name:  { label: 'Tên khách', align: 'left' },
  customer_phone: { label: 'ĐT khách', align: 'left' },
  receiving_time: { label: 'Giờ nhận', align: 'left' },
  delivery_time:  { label: 'Giờ giao', align: 'left' },
  items_table:    { label: 'Bảng món', align: 'left' },
  totals:         { label: 'Tổng tiền', align: 'left' },
  payment_status: { label: 'Trạng thái thanh toán', align: 'center' },
  qr_tracking:    { label: 'Mã QR tra cứu', align: 'center' },
  order_no:       { label: 'Số đơn', align: 'center' },
  custom_text:    { label: 'Văn bản tự do', align: 'center' },
  divider:        { label: 'Đường kẻ phân cách', align: 'center' },
  spacer:         { label: 'Khoảng trống', align: 'center' },
}

// Khối text có toggle IN NGHIÊNG (italic). Logo là ảnh → không.
export const ITALIC_TYPES = ['customer_name', 'customer_phone', 'receiving_time',
  'delivery_time', 'items_table', 'totals', 'payment_status', 'order_no', 'custom_text']
export const canItalic = (type) => ITALIC_TYPES.includes(type)

// Nhãn TEXT cố định mỗi khối (sửa được, song ngữ). key → {vi,en} mặc định.
// Bill fallback về default khi owner chưa sửa. Giá trị động KHÔNG ở đây.
// Stage 5.8: logo bỏ tiêu đề; qr bỏ caption; payment_status có 2 text trả/nợ.
export const BLOCK_LABELS = {
  customer_name: [{ key: 'label', vi: 'Tên', en: 'Name' }],
  customer_phone: [{ key: 'label', vi: 'ĐT', en: 'Tel' }],
  receiving_time: [{ key: 'label', vi: 'Giờ nhận', en: 'Receiving' }],
  delivery_time: [{ key: 'label', vi: 'Giờ giao', en: 'Delivery' }],
  items_table: [
    { key: 'svc', vi: 'Dịch vụ', en: 'Service' }, { key: 'qty', vi: 'SL', en: 'Qty' },
    { key: 'price', vi: 'Giá', en: 'Price' }, { key: 'total', vi: 'Tổng', en: 'Total' },
  ],
  totals: [
    { key: 'subtotal', vi: 'Tạm tính', en: 'Subtotal' },
    { key: 'surcharge', vi: 'Phụ thu', en: 'Surcharge' },
    { key: 'discount', vi: 'Giảm giá', en: 'Discount' },
    { key: 'total', vi: 'TỔNG CỘNG', en: 'TOTAL' },
  ],
  order_no: [{ key: 'label', vi: 'Số', en: 'No' }],
  // payment_status: 2 text owner sửa (đã trả / chưa trả).
  payment_status: [
    { key: 'paid', vi: 'ĐÃ THANH TOÁN', en: 'PAID' },
    { key: 'unpaid', vi: 'CHƯA THANH TOÁN', en: 'UNPAID' },
  ],
}

// Giá trị TEXT (không phải nhãn) owner nhập — field trong popup sửa.
export const BLOCK_VALUES = {
  custom_text: [{ key: 'vi', label: 'Nội dung (VI)', area: true }, { key: 'en', label: 'Nội dung (EN)', area: true, en: true }],
}

// Loại khối owner THÊM được (nhiều bản): văn bản tự do / đường kẻ / khoảng trống.
export const ADDABLE = [
  { type: 'custom_text', label: '＋ Văn bản tự do' },
  { type: 'divider', label: '＋ Đường kẻ' },
  { type: 'spacer', label: '＋ Khoảng trống' },
]

export const defaultAlign = (type) => BLOCK_META[type]?.align || 'left'

// ── Builder: chuyển đổi blocks[] ↔ rows (mảng hàng, mỗi hàng 1-2 khối) ──
// Tách ra lib để dùng chung + test được (Stage 5.10.1).
export function blocksToRows(blocks) {
  const map = new Map()
  blocks.forEach((b) => {
    const r = b.row ?? 0
    if (!map.has(r)) map.set(r, [])
    map.get(r).push(b)
  })
  return [...map.keys()].sort((a, b) => a - b)
    .map((k) => map.get(k).slice().sort((a, b) => (a.col === 'right' ? 1 : 0) - (b.col === 'right' ? 1 : 0)))
}

export function rowsToBlocks(rows) {
  const out = []
  rows.forEach((row, ri) => {
    if (row.length === 1) out.push({ ...row[0], row: ri, col: 'full' })
    else row.forEach((b, ci) => out.push({ ...b, row: ri, col: ci === 0 ? 'left' : 'right' }))
  })
  return out
}

// XÓA đúng 1 khối theo vị trí (ri,ci) — KHÔNG xóa khối khác cùng hàng (Stage 5.10.1).
// Hàng còn 1 khối → khối đó về col='full' (chiếm trọn hàng); hàng rỗng → bỏ hàng.
export function removeCellFromRows(rows, ri, ci) {
  const rs = rows.map((r) => r.slice())
  const row = rs[ri]
  if (!row) return rs
  row.splice(ci, 1)
  if (row.length === 0) rs.splice(ri, 1)
  else if (row.length === 1) row[0] = { ...row[0], col: 'full' }
  return rs
}

// Nhãn khối hiển thị trong danh sách builder. custom_text → nội dung rút gọn
// (~28 ký tự) để phân biệt nhiều khối; rỗng → "Văn bản tự do (trống)".
export function blockListLabel(blk) {
  if (blk.type === 'custom_text') {
    const txt = (blk.content?.vi || blk.content?.en || '').trim()
    if (!txt) return 'Văn bản tự do (trống)'
    return txt.length > 28 ? `${txt.slice(0, 28)}…` : txt
  }
  return BLOCK_META[blk.type]?.label || blk.type
}

// MẪU GỐC NỀN TẢNG (Stage 5.10): cấu trúc/định dạng chuẩn + PLACEHOLDER (không lộ
// thông tin tenant nào). Khối hệ thống `removable:false` → chỉ tắt, không xóa.
// (Frontend mirror của backend _default_blocks — backend là nguồn chính qua GET.)
function defaultBlocks() {
  const b = (id, type, extra = {}) => ({
    id, type, enabled: true, row: 0, col: 'full', removable: false, content: {}, ...extra,
  })
  return [
    b('logo', 'logo', { row: 0 }), // chỉ ảnh
    b('brand', 'custom_text', { row: 1, title: true, content: { vi: '[Tên tiệm]' } }),
    b('title', 'custom_text', { row: 2, bold: true, align: 'center', content: { vi: 'BIÊN NHẬN', en: 'RECEIPT' } }),
    b('customer_name', 'customer_name', { row: 3, col: 'left' }),
    b('customer_phone', 'customer_phone', { row: 3, col: 'right' }),
    b('receiving_time', 'receiving_time', { row: 4, col: 'left' }),
    b('delivery_time', 'delivery_time', { row: 4, col: 'right' }),
    b('items_table', 'items_table', { row: 5 }),
    b('totals', 'totals', { row: 6 }),
    b('note', 'custom_text', { row: 7, italic: true, size: 'small', content: {
      vi: 'Vui lòng giữ biên nhận và nhận đồ trong vòng 30 ngày kể từ ngày hẹn. Quá hạn, cơ sở không chịu trách nhiệm.',
      en: 'Please keep this receipt and collect within 30 days of the due date. After that we hold no responsibility.',
    } }),
    b('qr_tracking', 'qr_tracking', { row: 8 }),
    b('order_no', 'order_no', { row: 9 }),
    b('contact', 'custom_text', { row: 10, size: 'small', content: { vi: '[Địa chỉ] · [Số điện thoại]' } }),
    b('footer_thanks', 'custom_text', { row: 11, content: { vi: 'Cảm ơn quý khách!', en: 'Thank you!' } }),
  ]
}

export const DEFAULT_RECEIPT = { bilingual: true, logo_url: '', track_base_url: '', blocks: defaultBlocks(), branch_contact_blocks: {} }

// Bảo đảm cấu hình đủ field (rỗng/thiếu → mặc định). Backend đã migrate cấu hình
// cũ sang shape khối 5.8, nên client thường nhận sẵn blocks[] hợp lệ.
export function normalizeReceipt(cfg) {
  const c = cfg || {}
  const blocks = Array.isArray(c.blocks) && c.blocks.length ? c.blocks : defaultBlocks()
  // ⚠️ PHẢI giữ branch_contact_blocks — thiếu nó thì getReceiptConfig strip field →
  // Bill in mất khu "Liên hệ theo chi nhánh" (theo order.branch_id) cho MỌI CN.
  return {
    bilingual: c.bilingual !== false, logo_url: c.logo_url || '',
    track_base_url: c.track_base_url || '', blocks,
    branch_contact_blocks: c.branch_contact_blocks || {},
  }
}

let _cache = null
export function getReceiptConfig() {
  if (!_cache) {
    _cache = api
      .get('/settings/receipt')
      .then((c) => normalizeReceipt(c))
      .catch(() => DEFAULT_RECEIPT)
  }
  return _cache
}
// Xoá cache sau khi owner lưu cấu hình mới → lần in sau lấy bản mới.
export function clearReceiptCache() {
  _cache = null
}
