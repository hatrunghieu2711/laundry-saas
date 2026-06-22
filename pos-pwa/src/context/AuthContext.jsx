import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { clearSession, getUser, setSession } from '../lib/storage'

const AuthContext = createContext(null)

const ROLE_LABEL = {
  owner: 'Chủ chuỗi',
  manager: 'Quản lý',
  staff: 'Nhân viên',
  shipper: 'Shipper',
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(() => getUser())

  // Sau khi có token: lấy /auth/me + tên branch để hiển thị header.
  const hydrateUser = useCallback(async () => {
    const me = await api.me()
    let branchName = null
    if (me.branch_id) {
      try {
        const branch = await api.get(`/branches/${me.branch_id}`)
        branchName = branch.name
      } catch {
        branchName = null // không chặn login nếu không đọc được branch
      }
    }
    const full = { ...me, role_label: ROLE_LABEL[me.role] || me.role, branch_name: branchName }
    setSession({ user: full })
    setUser(full)
    // Tab title động theo TÊN TIỆM của user đang đăng nhập (pre-login giữ generic).
    if (full.tenant_name) document.title = `${full.tenant_name} POS`
    return full
  }, [])

  const login = useCallback(
    async (phone, password, slug) => {
      const tokens = await api.login(phone, password, slug)
      setSession({ access_token: tokens.access_token, csrf_token: tokens.csrf_token })
      return hydrateUser()
    },
    [hydrateUser],
  )

  const logout = useCallback(async () => {
    try {
      await api.logout()
    } catch {
      // kệ lỗi mạng — vẫn xoá phiên local
    }
    clearSession()
    setUser(null)
    document.title = 'POS'  // reset tab title về generic khi đăng xuất
  }, [])

  // Nếu mở app khi đã có phiên, validate lại nhẹ nhàng qua /auth/me.
  useEffect(() => {
    if (user) {
      hydrateUser().catch(() => {
        clearSession()
        setUser(null)
      })
    }
    // chạy một lần khi mount
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  return (
    <AuthContext.Provider value={{ user, login, logout }}>
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth phải dùng trong <AuthProvider>')
  return ctx
}
