// Cấu hình mẫu phiếu in (Stage 4.1 → nâng song ngữ 2H ở Stage 5.3).
// Layout phiếu CỐ ĐỊNH song ngữ Việt/Anh (nhãn cứng trong Bill.jsx). Owner chỉ
// sửa NỘI DUNG (text + logo ảnh) và bật/tắt 2 khối: ghi chú + phụ thu.
import { api } from './api'

export const DEFAULT_RECEIPT = {
  shop_name: 'Giặt Ủi 2H',
  logo_text: '2H',
  logo_url: '',
  hotline: '',
  web: '',
  address: '',
  zalo_wa_kakao: '',
  open_hours: '7:00 – 21:00 / Daily',
  footer_text: 'Cảm ơn quý khách! / Thank you!',
  note_enabled: true,
  note_vi:
    'Vui lòng giữ biên nhận và nhận đồ trong vòng 30 ngày kể từ ngày hẹn. ' +
    'Quá hạn, cơ sở không chịu trách nhiệm. Kiểm tra kỹ đồ trước khi rời tiệm.',
  note_en:
    'Please keep this receipt and collect your laundry within 30 days of the due ' +
    'date. After that we hold no responsibility. Please check your items before leaving.',
  surcharge_enabled: false,
  surcharge_percent: 0,
  surcharge_label_vi: 'Phụ thu Tết',
  surcharge_label_en: 'Holiday surcharge',
}

// Bảo đảm cấu hình luôn đủ field (cấu hình cũ thiếu field mới → lấy mặc định).
export function normalizeReceipt(cfg) {
  return { ...DEFAULT_RECEIPT, ...(cfg || {}) }
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
