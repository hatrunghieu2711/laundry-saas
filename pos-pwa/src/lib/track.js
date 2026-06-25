// Base URL trang tra cứu công khai (mirror hằng trong Bill.jsx). Link đầy đủ =
// DEFAULT_TRACK_BASE + {slug}/{order_code}; base (chỉ tới {slug}/) cho panel "Thông
// tin tiệm" để owner biết format + copy. Đổi domain → sửa cả đây và Bill.jsx.
export const DEFAULT_TRACK_BASE = 'https://track.giatui.app/track/'

// Link tra cứu CHUNG của tiệm (chưa kèm mã đơn) — base + slug + '/'.
export function tenantTrackBase(slug) {
  return slug ? `${DEFAULT_TRACK_BASE}${slug}/` : ''
}
