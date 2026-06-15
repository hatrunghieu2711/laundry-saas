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

// Metadata mỗi loại khối: nhãn quản lý, nhóm (text/dynamic), có ghép nửa hàng?
export const BLOCK_META = {
  logo:               { label: 'Logo & tiêu đề', kind: 'text', narrow: false },
  customer_info:      { label: 'Khách (Tên · ĐT)', kind: 'dynamic', narrow: false },
  receiving_time:     { label: 'Giờ nhận', kind: 'dynamic', narrow: true },
  delivery_time:      { label: 'Giờ giao', kind: 'dynamic', narrow: true },
  items_table:        { label: 'Bảng món', kind: 'dynamic', narrow: false },
  totals:             { label: 'Tổng tiền', kind: 'dynamic', narrow: false },
  surcharge_discount: { label: 'Phụ thu / Giảm (nổi bật)', kind: 'dynamic', narrow: false },
  payment_status:     { label: 'Trạng thái thanh toán', kind: 'dynamic', narrow: true },
  note:               { label: 'Ghi chú trách nhiệm', kind: 'text', narrow: false },
  qr_tracking:        { label: 'Mã QR tra cứu', kind: 'dynamic', narrow: false },
  order_no:           { label: 'Số đơn', kind: 'dynamic', narrow: true },
  footer_contact:     { label: 'Chân phiếu (liên hệ)', kind: 'text', narrow: false },
  custom_text:        { label: 'Văn bản tự do', kind: 'text', narrow: false },
}
// Loại khối owner có thể THÊM nhiều bản (chỉ custom_text). Khối khác là duy nhất.
export const ADDABLE_TYPES = ['custom_text']

export const isNarrow = (type) => !!BLOCK_META[type]?.narrow
export const isText = (type) => BLOCK_META[type]?.kind === 'text'

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
