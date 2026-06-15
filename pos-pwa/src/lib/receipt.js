// Cấu hình mẫu phiếu in — BILL BUILDER THEO KHỐI (Stage 5.6).
// receipt_config = { bilingual, logo_url, blocks[] }. Owner tự thêm/bớt/sắp xếp
// khối, ghép 2 khối hẹp/hàng, bật/tắt tiếng Anh. Nhãn song ngữ cứng ở Bill.jsx.
import { api } from './api'

export const DEFAULT_NOTE_VI =
  'Vui lòng giữ biên nhận và nhận đồ trong vòng 30 ngày kể từ ngày hẹn. ' +
  'Quá hạn, cơ sở không chịu trách nhiệm. Kiểm tra kỹ đồ trước khi rời tiệm.'
export const DEFAULT_NOTE_EN =
  'Please keep this receipt and collect your laundry within 30 days of the due ' +
  'date. After that we hold no responsibility. Please check your items before leaving.'

// Metadata mỗi loại khối: nhãn quản lý + căn lề mặc định khi render.
// (Stage 5.7: bỏ ràng buộc "narrow" — ghép TỰ DO 2 khối bất kỳ vào 1 hàng.)
export const BLOCK_META = {
  logo:               { label: 'Logo & tiêu đề', align: 'center' },
  customer_info:      { label: 'Khách (Tên · ĐT)', align: 'left' },
  receiving_time:     { label: 'Giờ nhận', align: 'left' },
  delivery_time:      { label: 'Giờ giao', align: 'left' },
  items_table:        { label: 'Bảng món', align: 'left' },
  totals:             { label: 'Tổng tiền', align: 'left' },
  surcharge_discount: { label: 'Phụ thu / Giảm (nổi bật)', align: 'left' },
  payment_status:     { label: 'Trạng thái thanh toán', align: 'center' },
  note:               { label: 'Ghi chú trách nhiệm', align: 'left' },
  qr_tracking:        { label: 'Mã QR tra cứu', align: 'center' },
  order_no:           { label: 'Số đơn', align: 'center' },
  footer_contact:     { label: 'Chân phiếu (liên hệ)', align: 'center' },
  custom_text:        { label: 'Văn bản tự do', align: 'center' },
  divider:            { label: 'Đường kẻ phân cách', align: 'center' },
  spacer:             { label: 'Khoảng trống', align: 'center' },
}

// Nhãn TEXT cố định mỗi khối (sửa được, song ngữ). key → {vi, en} mặc định
// = đúng text cứng hiện tại. Bill fallback về default khi owner chưa sửa.
export const BLOCK_LABELS = {
  logo: [{ key: 'title', vi: 'BIÊN NHẬN', en: 'RECEIPT' }],
  customer_info: [{ key: 'name', vi: 'Tên', en: 'Name' }, { key: 'tel', vi: 'ĐT', en: 'Tel' }],
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
  surcharge_discount: [
    { key: 'sur', vi: 'Phụ thu', en: 'Surcharge' }, { key: 'dis', vi: 'Đã giảm', en: 'Discount' },
  ],
  note: [{ key: 'label', vi: 'Lưu ý', en: 'Important Note' }],
  qr_tracking: [{ key: 'cap', vi: 'Quét mã QR', en: 'Scan QR to track' }],
  order_no: [{ key: 'label', vi: 'Số', en: 'No' }],
  footer_contact: [
    { key: 'lbl_hotline', vi: 'Hotline', en: 'Hotline' },
    { key: 'lbl_web', vi: 'Web', en: 'Web' },
    { key: 'lbl_address', vi: 'Địa chỉ', en: 'Add' },
    { key: 'lbl_zalo', vi: 'Zalo / WA / Kakao', en: 'Zalo / WA / Kakao' },
    { key: 'lbl_open', vi: 'Giờ mở cửa', en: 'OPEN' },
  ],
}

// Giá trị TEXT (không phải nhãn) owner nhập — field trong popup sửa.
export const BLOCK_VALUES = {
  logo: [{ key: 'shop_name', label: 'Tên tiệm' }, { key: 'logo_text', label: 'Logo chữ (khi chưa có ảnh)' }],
  note: [{ key: 'vi', label: 'Nội dung (VI)', area: true }, { key: 'en', label: 'Nội dung (EN)', area: true, en: true }],
  custom_text: [{ key: 'vi', label: 'Nội dung (VI)', area: true }, { key: 'en', label: 'Nội dung (EN)', area: true, en: true }],
  footer_contact: [
    { key: 'hotline', label: 'Hotline (giá trị)' }, { key: 'web', label: 'Web (giá trị)' },
    { key: 'address', label: 'Địa chỉ (giá trị)' }, { key: 'zalo_wa_kakao', label: 'Zalo/WA/Kakao (giá trị)' },
    { key: 'open_hours', label: 'Giờ mở cửa (giá trị)' }, { key: 'tagline', label: 'Dòng cảm ơn' },
  ],
}

// Loại khối owner THÊM được (nhiều bản). custom_text/divider/spacer.
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
    b('customer_info', 'customer_info', { row: 1 }),
    b('receiving_time', 'receiving_time', { row: 2, col: 'left' }),
    b('delivery_time', 'delivery_time', { row: 2, col: 'right' }),
    b('items_table', 'items_table', { row: 3 }),
    b('totals', 'totals', { row: 4 }),
    b('surcharge_discount', 'surcharge_discount', { row: 5, enabled: false }),
    b('note', 'note', { row: 6, content: { vi: DEFAULT_NOTE_VI, en: DEFAULT_NOTE_EN } }),
    b('qr_tracking', 'qr_tracking', { row: 7 }),
    b('order_no', 'order_no', { row: 8, col: 'left' }),
    b('payment_status', 'payment_status', { row: 8, col: 'right', enabled: false }),
    b('footer_contact', 'footer_contact', {
      row: 9,
      content: {
        hotline: '', web: '', address: '', zalo_wa_kakao: '',
        open_hours: '7:00 – 21:00 / Daily', tagline: 'Cảm ơn quý khách! / Thank you!',
      },
    }),
  ]
}

export const DEFAULT_RECEIPT = { bilingual: true, logo_url: '', blocks: defaultBlocks() }

// Bảo đảm cấu hình đủ field (cấu hình rỗng/thiếu → mặc định). Backend đã migrate
// cấu hình cũ sang shape khối, nên client thường nhận sẵn blocks[].
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
