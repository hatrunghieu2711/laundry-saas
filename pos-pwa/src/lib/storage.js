// Lưu phiên trong localStorage (pattern Phase 2L): access_token + csrf + user.
// refresh_token KHÔNG ở đây — nó nằm trong cookie httpOnly do backend set.
const K = {
  access: 'pos.access_token',
  csrf: 'pos.csrf',
  user: 'pos.user',
  // Mã cửa hàng (slug tenant) — BỀN qua logout: mỗi máy POS nhớ mã, lần sau tự điền.
  // KHÔNG xóa trong clearSession; chỉ đổi khi user nhập mã khác lúc đăng nhập.
  tenantSlug: 'pos.tenant_slug',
  // Token Super Admin (khu /admin) — TÁCH HẲN token POS (pos.access_token) để admin
  // và owner cùng máy không đá nhau. A1 access-token only (không refresh/csrf).
  adminToken: 'pos.admin_token',
}

export const getAccessToken = () => localStorage.getItem(K.access)
export const getCsrf = () => localStorage.getItem(K.csrf)

export const getTenantSlug = () => localStorage.getItem(K.tenantSlug) || ''
export function setTenantSlug(slug) {
  if (slug) localStorage.setItem(K.tenantSlug, slug)
  else localStorage.removeItem(K.tenantSlug)
}

export function getUser() {
  const raw = localStorage.getItem(K.user)
  if (!raw) return null
  try {
    return JSON.parse(raw)
  } catch {
    return null
  }
}

export function setSession({ access_token, csrf_token, user }) {
  if (access_token !== undefined) localStorage.setItem(K.access, access_token)
  if (csrf_token !== undefined) localStorage.setItem(K.csrf, csrf_token)
  if (user !== undefined) localStorage.setItem(K.user, JSON.stringify(user))
}

export function clearSession() {
  // Chỉ xóa phiên POS — KHÔNG đụng admin token (phiên admin tách biệt).
  localStorage.removeItem(K.access)
  localStorage.removeItem(K.csrf)
  localStorage.removeItem(K.user)
}

// ── Phiên Super Admin (/admin) — RIÊNG, không lẫn POS ───────────────────────
export const getAdminToken = () => localStorage.getItem(K.adminToken)
export function setAdminToken(token) {
  if (token) localStorage.setItem(K.adminToken, token)
  else localStorage.removeItem(K.adminToken)
}
export function clearAdminSession() {
  // Chỉ xóa token admin — KHÔNG đụng phiên POS.
  localStorage.removeItem(K.adminToken)
}
