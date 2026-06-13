import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Layout chung: header (branch + user + logout) + nội dung.
export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()

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
      <main className="app-main">{children}</main>
    </div>
  )
}
