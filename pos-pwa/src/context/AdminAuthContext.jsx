import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { clearAdminSession, getAdminToken, setAdminToken } from '../lib/storage'

// Auth Super Admin — TÁCH HẲN AuthContext POS (token khác, /me khác, KHÔNG refresh).
const AdminAuthContext = createContext(null)

export function AdminAuthProvider({ children }) {
  const [admin, setAdmin] = useState(null)
  const [ready, setReady] = useState(false) // chưa hydrate xong → guard chờ (tránh đá ra login oan)

  // Mở app /admin: có token cũ → xác thực lại qua /admin/me; hỏng → xóa phiên.
  const hydrate = useCallback(async () => {
    if (!getAdminToken()) {
      setAdmin(null)
      setReady(true)
      return
    }
    try {
      setAdmin(await api.admin.me())
    } catch {
      clearAdminSession()
      setAdmin(null)
    } finally {
      setReady(true)
    }
  }, [])

  useEffect(() => {
    hydrate()
  }, [hydrate])

  const login = useCallback(async (phone, password) => {
    const tokens = await api.admin.login(phone, password)
    setAdminToken(tokens.access_token)
    const me = await api.admin.me()
    setAdmin(me)
    return me
  }, [])

  const logout = useCallback(() => {
    clearAdminSession()
    setAdmin(null)
  }, [])

  return (
    <AdminAuthContext.Provider value={{ admin, ready, login, logout }}>
      {children}
    </AdminAuthContext.Provider>
  )
}

export function useAdminAuth() {
  const ctx = useContext(AdminAuthContext)
  if (!ctx) throw new Error('useAdminAuth phải dùng trong <AdminAuthProvider>')
  return ctx
}
