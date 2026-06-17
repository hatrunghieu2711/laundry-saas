import { useEffect, useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { useTopbarSlot } from '../context/TopbarSlotContext'

// Nav chính: + Tạo đơn · Đơn hàng · Ca · ☰ (menu). (Tab "Tra cứu" thêm ở Stage 6.11.)
const NAV = [
  { to: '/orders/new', label: '＋ Tạo đơn', end: false },
  { to: '/board', label: 'Đơn hàng', end: false },
  { to: '/', label: 'Ca', end: true },
]
// Mục trong menu ☰ (chừa chỗ thêm sau).
const MENU = [
  { to: '/cashbook', label: '💵 Sổ quỹ' },
  { to: '/reports', label: '📊 Báo cáo', roles: ['owner'] },
  { to: '/services', label: '💰 Bảng giá', roles: ['owner', 'manager'] },
  { to: '/categories', label: '🗂️ Danh mục', roles: ['owner', 'manager'] },
  { to: '/users', label: '👥 Nhân viên', roles: ['owner', 'manager'] },
  { to: '/price-rules', label: '🏷️ Phụ thu / Giảm giá', roles: ['owner'] },
  { to: '/settings/receipt', label: '🧾 Mẫu phiếu in', roles: ['owner', 'manager'] },
  { to: '/branches', label: '🏢 Chi nhánh', roles: ['owner'] },
]

export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { branchId, setBranchId, branches } = useBranch()
  const { setSlotEl } = useTopbarSlot()
  const isOwner = user?.role === 'owner'
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
      {/* Header GỌN 1 dòng (Stage 6.6): tab trái · chi nhánh + ☰ phải.
          Tên tiệm / tài khoản / Đăng xuất chuyển vào menu ☰ để tiết kiệm chiều cao. */}
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
        <div className="app-nav__spacer" />
        {/* Ô để trang hiện hành portal controls (search + làm mới) vào. */}
        <div className="app-nav__slot" ref={setSlotEl} />
        {isOwner && branches.length > 0 ? (
          // Chủ: bộ chọn CN DÙNG CHUNG mọi màn (Đơn hàng, Ca, Tra cứu…).
          <select
            className="app-nav__branch app-nav__branch--select"
            value={branchId || ''}
            onChange={(e) => setBranchId(e.target.value || null)}
            aria-label="Chọn chi nhánh"
          >
            <option value="">Tất cả CN</option>
            {branches.map((b) => (
              <option key={b.id} value={b.id}>
                {b.code} · {b.name}
              </option>
            ))}
          </select>
        ) : user?.branch_name ? (
          <span className="app-nav__branch" title={user.branch_name}>
            {user.branch_name}
          </span>
        ) : null}
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
              <div className="app-menu__head">
                <strong>{user?.full_name || 'Giặt Ủi 2H'}</strong>
                <small>
                  {user?.role_label}
                  {user?.branch_name ? ` · ${user.branch_name}` : ''}
                </small>
              </div>
              {menuItems.map((m) => (
                <button key={m.to} className="app-menu__item" onClick={() => go(m.to)}>
                  {m.label}
                </button>
              ))}
              <button className="app-menu__item app-menu__logout" onClick={handleLogout}>
                ↪ Đăng xuất
              </button>
            </div>
          )}
        </div>
      </nav>
      <main className="app-main">{children}</main>
    </div>
  )
}
