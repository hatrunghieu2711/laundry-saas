import { Navigate } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'

// Guard khu /admin: chưa đăng nhập admin → /admin/login. Chờ hydrate xong (ready)
// để không đá ra login oan khi reload trang có token hợp lệ.
export default function AdminProtectedRoute({ children }) {
  const { admin, ready } = useAdminAuth()
  if (!ready) return <p className="shift__hint" style={{ padding: 16 }}>Đang tải…</p>
  if (!admin) return <Navigate to="/admin/login" replace />
  return children
}
