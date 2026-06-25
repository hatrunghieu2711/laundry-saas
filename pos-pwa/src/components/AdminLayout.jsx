import { NavLink, useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../context/AdminAuthContext'

// Tab nav khu /admin: đậm + gạch dưới khi active.
const navStyle = ({ isActive }) => ({
  fontSize: 14, fontWeight: isActive ? 700 : 500,
  color: isActive ? 'var(--text, #111827)' : 'var(--muted, #6b7280)',
  textDecoration: 'none', paddingBottom: 2,
  borderBottom: isActive ? '2px solid currentColor' : '2px solid transparent',
})

// Layout khu /admin — header gọn + nav + nội dung. KHÔNG dùng Layout/menu POS.
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
        <div style={{ display: 'flex', alignItems: 'center', gap: 16 }}>
          <strong style={{ fontSize: 16, cursor: 'pointer' }} onClick={() => navigate('/admin')}>
            Quản trị hệ thống
          </strong>
          <nav style={{ display: 'flex', gap: 14 }}>
            <NavLink to="/admin" end style={navStyle}>Tổng quan</NavLink>
            <NavLink to="/admin/tenants" style={navStyle}>Cửa hàng</NavLink>
            <NavLink to="/admin/default-receipt" style={navStyle}>Mẫu in</NavLink>
          </nav>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
          {admin?.full_name && <span className="shift__hint">{admin.full_name}</span>}
          <button className="btn btn--ghost btn--sm" onClick={onLogout}>Đăng xuất</button>
        </div>
      </header>
      <main>{children}</main>
    </div>
  )
}
