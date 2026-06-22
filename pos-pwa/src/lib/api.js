// API client: base /api/v1, tự gắn Bearer, refresh-on-401 (single-flight) + retry.
import {
  clearAdminSession,
  clearSession,
  getAccessToken,
  getAdminToken,
  getCsrf,
  setSession,
} from './storage'

const BASE = '/api/v1'

export class ApiError extends Error {
  constructor(status, code, message) {
    super(message)
    this.status = status
    this.code = code
  }
}

function redirectToLogin() {
  if (window.location.pathname !== '/login') {
    window.location.assign('/login')
  }
}

async function parseJson(resp) {
  try {
    return await resp.json()
  } catch {
    return null
  }
}

// Single-flight refresh: nhiều request 401 cùng lúc chỉ refresh MỘT lần.
let refreshing = null

async function doRefresh() {
  const csrf = getCsrf()
  const resp = await fetch(`${BASE}/auth/refresh`, {
    method: 'POST',
    credentials: 'include', // gửi cookie refresh_token (httpOnly) + csrf
    headers: csrf ? { 'X-CSRF-Token': csrf } : {},
  })
  if (!resp.ok) throw new Error('refresh failed')
  const data = await resp.json()
  setSession({ access_token: data.access_token, csrf_token: data.csrf_token })
  return data.access_token
}

function refreshOnce() {
  if (!refreshing) {
    refreshing = doRefresh().finally(() => {
      refreshing = null
    })
  }
  return refreshing
}

const NO_REFRESH = new Set(['/auth/login', '/auth/refresh'])

export async function apiFetch(
  path,
  { method = 'GET', body, headers = {}, auth = true, _retry = false } = {},
) {
  const h = { ...headers }
  const token = getAccessToken()
  if (auth && token) h['Authorization'] = `Bearer ${token}`

  const init = { method, headers: h, credentials: 'include' }
  if (body !== undefined && body !== null) {
    h['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }

  const resp = await fetch(`${BASE}${path}`, init)

  // 401 → thử refresh một lần rồi retry request gốc.
  if (resp.status === 401 && auth && !_retry && !NO_REFRESH.has(path)) {
    try {
      await refreshOnce()
    } catch {
      clearSession()
      redirectToLogin()
      throw new ApiError(401, 'SESSION_EXPIRED', 'Phiên đăng nhập đã hết hạn')
    }
    return apiFetch(path, { method, body, headers, auth, _retry: true })
  }

  const data = await parseJson(resp)
  if (!resp.ok) {
    if (resp.status === 401) {
      clearSession()
      redirectToLogin()
    }
    throw new ApiError(
      resp.status,
      data?.code || 'ERROR',
      data?.message || 'Có lỗi xảy ra, thử lại sau',
    )
  }
  return data
}

// Upload multipart (FormData) — KHÔNG set Content-Type (browser tự gắn boundary),
// nên không dùng được apiFetch (vốn JSON.stringify). Tự xử lý refresh-on-401 1 lần.
export async function apiUpload(path, formData, { _retry = false } = {}) {
  const token = getAccessToken()
  const headers = {}
  if (token) headers['Authorization'] = `Bearer ${token}`

  const resp = await fetch(`${BASE}${path}`, {
    method: 'POST',
    headers,
    body: formData,
    credentials: 'include',
  })

  if (resp.status === 401 && !_retry) {
    try {
      await refreshOnce()
    } catch {
      clearSession()
      redirectToLogin()
      throw new ApiError(401, 'SESSION_EXPIRED', 'Phiên đăng nhập đã hết hạn')
    }
    return apiUpload(path, formData, { _retry: true })
  }

  const data = await parseJson(resp)
  if (!resp.ok) {
    if (resp.status === 401) {
      clearSession()
      redirectToLogin()
    }
    throw new ApiError(resp.status, data?.code || 'ERROR', data?.message || 'Tải lên thất bại')
  }
  return data
}

// ── Super Admin client (/api/v1/admin/*) — TÁCH HẲN apiFetch POS ────────────
// Dùng admin token (pos.admin_token), KHÔNG refresh (A1 access-only), 401 → xóa
// phiên admin + về /admin/login (KHÔNG redirect /login POS).
function redirectToAdminLogin() {
  if (window.location.pathname !== '/admin/login') {
    window.location.assign('/admin/login')
  }
}

async function adminFetch(path, { method = 'GET', body, auth = true } = {}) {
  const h = {}
  const token = getAdminToken()
  if (auth && token) h['Authorization'] = `Bearer ${token}`
  const init = { method, headers: h }
  if (body !== undefined && body !== null) {
    h['Content-Type'] = 'application/json'
    init.body = JSON.stringify(body)
  }
  const resp = await fetch(`${BASE}/admin${path}`, init)
  const data = await parseJson(resp)
  if (!resp.ok) {
    if (resp.status === 401 && auth) {
      clearAdminSession()
      redirectToAdminLogin()
    }
    throw new ApiError(resp.status, data?.code || 'ERROR', data?.message || 'Có lỗi xảy ra, thử lại sau')
  }
  return data
}

export const api = {
  get: (path, opts) => apiFetch(path, { ...opts, method: 'GET' }),
  post: (path, body, opts) => apiFetch(path, { ...opts, method: 'POST', body }),
  upload: (path, formData) => apiUpload(path, formData),
  put: (path, body, opts) => apiFetch(path, { ...opts, method: 'PUT', body }),
  patch: (path, body, opts) => apiFetch(path, { ...opts, method: 'PATCH', body }),
  del: (path, opts) => apiFetch(path, { ...opts, method: 'DELETE' }),

  // ── auth shortcuts ──
  // slug (mã cửa hàng) optional — chỉ gửi khi có (client cũ/không nhập → không gửi).
  login: (phone, password, slug) =>
    apiFetch('/auth/login', {
      method: 'POST',
      body: { phone, password, ...(slug ? { slug } : {}) },
      auth: false,
    }),
  me: () => apiFetch('/auth/me'),
  logout: () => apiFetch('/auth/logout', { method: 'POST' }),
  // Tự đổi MK (Bearer auth + gửi cookie để BE chừa phiên hiện tại khi revoke).
  changePassword: (current_password, new_password) =>
    apiFetch('/auth/change-password', {
      method: 'POST',
      body: { current_password, new_password },
    }),

  // ── Super Admin (/admin) — token RIÊNG, không refresh ──
  admin: {
    login: (phone, password) =>
      adminFetch('/auth/login', { method: 'POST', body: { phone, password }, auth: false }),
    me: () => adminFetch('/me'),
    listTenants: () => adminFetch('/tenants'),
    getTenant: (id) => adminFetch(`/tenants/${id}`),
    createTenant: (body) => adminFetch('/tenants', { method: 'POST', body }),
    updateTenant: (id, body) => adminFetch(`/tenants/${id}`, { method: 'PATCH', body }),
    lockTenant: (id) => adminFetch(`/tenants/${id}/lock`, { method: 'POST' }),
    unlockTenant: (id) => adminFetch(`/tenants/${id}/unlock`, { method: 'POST' }),
    resetOwnerPassword: (id, user_id) =>
      adminFetch(`/tenants/${id}/reset-owner-password`, {
        method: 'POST',
        body: user_id ? { user_id } : {},
      }),
  },
}
