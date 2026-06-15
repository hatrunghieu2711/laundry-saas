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
  logo:           { label: 'Logo & tiêu đề', align: 'center' },
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

// Nhãn TEXT cố định mỗi khối (sửa được, song ngữ). key → {vi,en} mặc định.
// Bill fallback về default khi owner chưa sửa. Giá trị động KHÔNG ở đây.
export const BLOCK_LABELS = {
  logo: [{ key: 'title', vi: 'BIÊN NHẬN', en: 'RECEIPT' }],
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
    { key: 'discount', vi: 'Giảm', en: 'Discount' },
    { key: 'total', vi: 'TỔNG CỘNG', en: 'TOTAL' },
  ],
  qr_tracking: [{ key: 'cap', vi: 'Quét mã QR', en: 'Scan QR to track' }],
  order_no: [{ key: 'label', vi: 'Số', en: 'No' }],
}

// Giá trị TEXT (không phải nhãn) owner nhập — field trong popup sửa.
export const BLOCK_VALUES = {
  logo: [{ key: 'shop_name', label: 'Tên tiệm' }, { key: 'logo_text', label: 'Logo chữ (khi chưa có ảnh)' }],
  custom_text: [{ key: 'vi', label: 'Nội dung (VI)', area: true }, { key: 'en', label: 'Nội dung (EN)', area: true, en: true }],
}

// Loại khối owner THÊM được (nhiều bản): văn bản tự do / đường kẻ / khoảng trống.
export const ADDABLE = [
  { type: 'custom_text', label: '＋ Văn bản tự do' },
  { type: 'divider', label: '＋ Đường kẻ' },
  { type: 'spacer', label: '＋ Khoảng trống' },
]

export const defaultAlign = (type) => BLOCK_META[type]?.align || 'left'

function defaultBlocks() {
  const b = (id, type, extra = {}) => ({
    id, type, enabled: true, row: 0, col: 'full', content: {}, ...extra,
  })
  return [
    b('logo', 'logo', { row: 0, content: { shop_name: 'Giặt Ủi 2H', logo_text: '2H' } }),
    b('customer_name', 'customer_name', { row: 1, col: 'left' }),
    b('customer_phone', 'customer_phone', { row: 1, col: 'right' }),
    b('receiving_time', 'receiving_time', { row: 2, col: 'left' }),
    b('delivery_time', 'delivery_time', { row: 2, col: 'right' }),
    b('items_table', 'items_table', { row: 3 }),
    b('totals', 'totals', { row: 4 }),
    b('qr_tracking', 'qr_tracking', { row: 5 }),
    b('order_no', 'order_no', { row: 6 }),
    b('footer_thanks', 'custom_text', { row: 7, content: { vi: 'Cảm ơn quý khách!', en: 'Thank you!' } }),
  ]
}

export const DEFAULT_RECEIPT = { bilingual: true, logo_url: '', blocks: defaultBlocks() }

// Bảo đảm cấu hình đủ field (rỗng/thiếu → mặc định). Backend đã migrate cấu hình
// cũ sang shape khối 5.8, nên client thường nhận sẵn blocks[] hợp lệ.
export function normalizeReceipt(cfg) {
  const c = cfg || {}
  const blocks = Array.isArray(c.blocks) && c.blocks.length ? c.blocks : defaultBlocks()
  return { bilingual: c.bilingual !== false, logo_url: c.logo_url || '', blocks }
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
