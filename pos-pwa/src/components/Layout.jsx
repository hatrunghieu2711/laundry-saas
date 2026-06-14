import { useEffect, useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Nav chính (Stage 3.9): + Tạo đơn · Đơn hàng · Ca · ☰ (menu).
const NAV = [
  { to: '/orders/new', label: '＋ Tạo đơn', end: false },
  { to: '/board', label: 'Đơn hàng', end: false },
  { to: '/', label: 'Ca', end: true },
]
// Mục trong menu ☰ (chừa chỗ thêm sau).
const MENU = [
  { to: '/cashbook', label: '💵 Sổ quỹ' },
  { to: '/services', label: '💰 Bảng giá', roles: ['owner', 'manager'] },
  { to: '/settings/receipt', label: '🧾 Mẫu phiếu in', roles: ['owner', 'manager'] },
]

export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

  const menuItems = MENU.filter((m) => !m.roles || m.roles.includes(user?.role))

  // Đóng menu khi bấm ra ngoài.
  useEffect(() => {
    if (!menuOpen) return undefined
    const onDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuOpen(false)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [menuOpen])

  const handleLogout = async () => {
    await logout()
    navigate('/login', { replace: true })
  }

  const go = (to) => {
    setMenuOpen(false)
    navigate(to)
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
        {NAV.map((n) => (
          <NavLink
            key={n.to}
            to={n.to}
            end={n.end}
            className={({ isActive }) => `app-nav__tab ${isActive ? 'app-nav__tab--active' : ''}`}
          >
            {n.label}
          </NavLink>
        ))}
        <div className="app-nav__menu" ref={menuRef}>
          <button
            className={`app-nav__tab app-nav__more ${menuOpen ? 'app-nav__tab--active' : ''}`}
            onClick={() => setMenuOpen((o) => !o)}
            aria-label="Menu"
          >
            ☰
          </button>
          {menuOpen && (
            <div className="app-menu">
              {menuItems.length === 0 ? (
                <div className="app-menu__empty">Không có mục nào</div>
              ) : (
                menuItems.map((m) => (
                  <button key={m.to} className="app-menu__item" onClick={() => go(m.to)}>
                    {m.label}
                  </button>
                ))
              )}
            </div>
          )}
        </div>
      </nav>
      <main className="app-main">{children}</main>
    </div>
  )
}
