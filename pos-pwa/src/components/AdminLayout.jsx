import { useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'

// Layout khu /admin — header gọn + nội dung. KHÔNG dùng Layout/menu POS.
export default function AdminLayout({ children }) {
  const { admin, logout } = useAdminAuth()
  const navigate = useNavigate()

  const onLogout = () => {
    logout()
    navigate('/admin/login', { replace: true })
  }

  return (
    <div style={{ maxWidth: 880, margin: '0 auto', padding: 16 }}>
      <header
        style={{
          display: 'flex', alignItems: 'center', justifyContent: 'space-between',
          gap: 12, marginBottom: 16, paddingBottom: 12, borderBottom: '1px solid var(--line)',
        }}
      >
        <strong
          style={{ fontSize: 16, cursor: 'pointer' }}
          onClick={() => navigate('/admin')}
        >
          Quản trị hệ thống
        </strong>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {admin?.full_name && <span className="shift__hint">{admin.full_name}</span>}
          <button className="btn btn--ghost btn--sm" onClick={onLogout}>Đăng xuất</button>
        </div>
      </header>
      <main>{children}</main>
    </div>
  )
}
