// Lưu phiên trong localStorage (pattern Phase 2L): access_token + csrf + user.
// refresh_token KHÔNG ở đây — nó nằm trong cookie httpOnly do backend set.
const K = {
  access: 'pos.access_token',
  csrf: 'pos.csrf',
  user: 'pos.user',
}

export const getAccessToken = () => localStorage.getItem(K.access)
export const getCsrf = () => localStorage.getItem(K.csrf)

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
  localStorage.removeItem(K.access)
  localStorage.removeItem(K.csrf)
  localStorage.removeItem(K.user)
}
