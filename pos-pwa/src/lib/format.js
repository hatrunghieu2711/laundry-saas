// Helper định dạng dùng chung.

// QUAN TRỌNG: field tiền từ API có thể là notation khoa học ("5E+4").
// LUÔN Number() trước khi format — không hiển thị raw string.
// (Xem CLAUDE.md mục "Nợ kỹ thuật đã biết".)
export function formatVND(value) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '0đ'
  return new Intl.NumberFormat('vi-VN').format(Math.round(n)) + 'đ'
}

// Số nguyên an toàn từ giá trị tiền API (cho tính toán).
export function toNumber(value) {
  const n = Number(value)
  return Number.isFinite(n) ? n : 0
}

export function formatDateTime(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  return new Intl.DateTimeFormat('vi-VN', {
    hour: '2-digit',
    minute: '2-digit',
    day: '2-digit',
    month: '2-digit',
    year: 'numeric',
  }).format(d)
}
