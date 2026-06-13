import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

const NAV = [
  { to: '/', label: 'Ca', end: true },
  { to: '/board', label: 'Bảng đơn', end: false },
  { to: '/orders', label: 'Đơn', end: false },
  { to: '/orders/new', label: '＋ Tạo đơn', end: false },
  { to: '/services', label: 'Bảng giá', end: false, roles: ['owner', 'manager'] },
]

// Layout chung: header (branch + user + logout) + nội dung.
export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const nav = NAV.filter((n) => !n.roles || n.roles.includes(user?.role))

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  return (
    <div className="app-shell">
      <header className="app-header">
        <div className="app-header__brand">
          <span className="app-header__logo">2H</span>
          <div className="app-header__titles">
            <strong>{user?.branch_name || 'Giặt Ủi 2H'}</strong>
            <small>
              {user?.full_name} · {user?.role_label}
            </small>
          </div>
        </div>
        <button className="btn btn--ghost btn--sm" onClick={handleLogout}>
          Đăng xuất
        </button>
      </header>
      <nav className="app-nav">
        {nav.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => `app-nav__tab ${isActive ? 'app-nav__tab--active' : ''}`}
          >
            {n.label}
          </NavLink>
        ))}
      </nav>
      <main className="app-main">{children}</main>
    </div>
  )
}
