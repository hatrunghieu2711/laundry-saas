// Cấu hình mẫu phiếu in (Stage 4.1). Đọc từ GET /settings/receipt (cache 1 lần).
import { api } from './api'

export const RECEIPT_BLOCKS = [
  { key: 'header', label: 'Tiêu đề (logo · tên · địa chỉ · SĐT)' },
  { key: 'order_code', label: 'Mã đơn' },
  { key: 'pickup_time', label: 'Giờ hẹn lấy' },
  { key: 'qr_tracking', label: 'Mã QR tra cứu' },
  { key: 'items', label: 'Danh sách dịch vụ' },
  { key: 'totals', label: 'Tổng · Đã thu · Còn lại' },
  { key: 'payment_status', label: 'Trạng thái thanh toán' },
  { key: 'meta', label: 'Khách hàng · ngày lập' },
  { key: 'footer', label: 'Lời cảm ơn · giờ mở cửa' },
]
export const BLOCK_LABEL = Object.fromEntries(RECEIPT_BLOCKS.map((b) => [b.key, b.label]))

export const DEFAULT_RECEIPT = {
  shop_name: 'Giặt Ủi 2H',
  address: '',
  phone: '',
  footer_text: 'Cảm ơn quý khách!',
  open_hours: '7:00 – 21:00 hằng ngày',
  logo_text: '2H',
  blocks: RECEIPT_BLOCKS.map((b, i) => ({ key: b.key, enabled: true, order: i })),
}

// Bảo đảm đủ field + blocks sort theo order (và bổ sung khối thiếu vào cuối).
export function normalizeReceipt(cfg) {
  const c = { ...DEFAULT_RECEIPT, ...(cfg || {}) }
  let blocks = Array.isArray(cfg?.blocks) && cfg.blocks.length ? [...cfg.blocks] : DEFAULT_RECEIPT.blocks
  const have = new Set(blocks.map((b) => b.key))
  let nxt = blocks.reduce((m, b) => Math.max(m, b.order ?? 0), -1) + 1
  for (const b of RECEIPT_BLOCKS) {
    if (!have.has(b.key)) blocks.push({ key: b.key, enabled: true, order: nxt++ })
  }
  blocks = [...blocks].sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
  return { ...c, blocks }
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
