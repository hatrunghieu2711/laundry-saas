import { Fragment, useEffect, useRef, useState } from 'react'
import { NavLink, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { useShift } from '../context/ShiftContext'
import { useTopbarSlot } from '../context/TopbarSlotContext'

// Nav chính: + Tạo đơn · Đơn hàng · Ca · Lịch sử · ☰ (menu).
const NAV = [
  { to: '/orders/new', label: '＋ Tạo đơn', end: false },
  { to: '/board', label: 'Đơn hàng', end: false },
  { to: '/', label: 'Ca', end: true },
  { to: '/history', label: 'Lịch sử', end: false },
]
// Menu ☰ chia NHÓM (icon = INLINE SVG, không emoji/webfont). Mỗi section: title (tùy
// chọn, không bấm) + items lọc theo role. Section rỗng (role không có item) → ẩn cả title.
const MENU_SECTIONS = [
  {
    items: [
      { to: '/cashbook', label: 'Sổ quỹ', icon: 'cashbook' },
      { to: '/reports', label: 'Báo cáo', icon: 'reports', roles: ['owner'] },
    ],
  },
  {
    title: 'Quản lý',
    items: [
      { to: '/settings/shop', label: 'Cài đặt tiệm', icon: 'store', roles: ['owner'] },
      { to: '/branches', label: 'Chi nhánh', icon: 'branches', roles: ['owner'] },
      { to: '/users', label: 'Nhân viên', icon: 'users', roles: ['owner', 'manager'] },
      // Gom 4 màn (Danh mục/Dịch vụ&giá/Phụ thu&giảm/Hiển thị theo CN) → 1 hub tab.
      { to: '/catalog', label: 'Dịch vụ & bảng giá', icon: 'services', roles: ['owner', 'manager'] },
      { to: '/settings/receipt', label: 'Mẫu phiếu in', icon: 'receipt', roles: ['owner', 'manager'] },
    ],
  },
  {
    // Tài khoản — mọi role. Đăng xuất render riêng (nút danh nghĩa đỏ) sau các section.
    items: [{ to: '/account/password', label: 'Đổi mật khẩu', icon: 'key' }],
  },
]

// Icon SVG inline (kiểu line-icon) — KHÔNG webfont/emoji, hợp PWA offline + Chrome 56.
const ICON_PATHS = {
  cashbook: 'M3 7a2 2 0 0 1 2-2h12a2 2 0 0 1 2 2 M3 7v10a2 2 0 0 0 2 2h13a1 1 0 0 0 1-1v-3 M21 11h-4a2 2 0 0 0 0 4h4z',
  reports: 'M4 4v16h16 M8 14v3 M12 9v8 M16 12v5',
  services: 'M12 2v20 M16 6H10a3 3 0 0 0 0 6h4a3 3 0 0 1 0 6H8',
  categories: 'M4 4h7v7H4z M13 4h7v7h-7z M4 13h7v7H4z M13 13h7v7h-7z',
  users: 'M20 21v-2a4 4 0 0 0-4-4H8a4 4 0 0 0-4 4v2 M12 11a4 4 0 1 0 0-8 4 4 0 0 0 0 8',
  pricerules: 'M19 5L5 19 M7 7a1.5 1.5 0 1 0 0.01 0 M17 17a1.5 1.5 0 1 0 0.01 0',
  receipt: 'M5 3h14v18l-3-2-2 2-2-2-2 2-3-2z M8 8h8 M8 12h8 M8 16h5',
  branches: 'M4 21V8l8-5 8 5v13 M4 21h16 M9 21v-6h6v6',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  logout: 'M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4 M16 17l5-5-5-5 M21 12H9',
  key: 'M14 7a4 4 0 1 0-3.5 6.9L9 15.5V18H6.5L4 20.5 M14 7l6 6 M11.5 9.5l8.5 8.5',
  store: 'M4 9l1.5-5h13L20 9 M4 9h16 M5 9v11h14V9 M10 20v-5h4v5',
  eye: 'M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7-10-7-10-7z M12 15a3 3 0 1 0 0-6 3 3 0 0 0 0 6z',
}
function NavIcon({ name }) {
  return (
    <svg
      className="app-menu__ic" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  )
}

export default function Layout({ children }) {
  const { user, logout } = useAuth()
  const navigate = useNavigate()
  const { branchId, setBranchId, branches } = useBranch()
  const { shiftOpen } = useShift()
  const { setSlotEl } = useTopbarSlot()
  // Nhãn tab "Ca" động (6.71): đang mở → "Đóng ca"; chưa mở → "Mở ca"; chưa biết → "Ca".
  const caLabel = shiftOpen === true ? 'Đóng ca' : shiftOpen === false ? 'Mở ca' : 'Ca'
  const isOwner = user?.role === 'owner'
  const [menuOpen, setMenuOpen] = useState(false)
  const menuRef = useRef(null)

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
            {n.to === '/' ? caLabel : n.label}
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
                {b.order_prefix} · {b.name}
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
            <NavIcon name="menu" />
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
              {MENU_SECTIONS.map((sec, si) => {
                const items = sec.items.filter((m) => !m.roles || m.roles.includes(user?.role))
                if (!items.length) return null
                return (
                  <Fragment key={si}>
                    {sec.title ? (
                      <div className="app-menu__group-title">{sec.title}</div>
                    ) : si > 0 ? (
                      <div className="app-menu__divider" />
                    ) : null}
                    {items.map((m) => (
                      <button key={m.to} className="app-menu__item" onClick={() => go(m.to)}>
                        <NavIcon name={m.icon} />{m.label}
                      </button>
                    ))}
                  </Fragment>
                )
              })}
              <button className="app-menu__item app-menu__logout" onClick={handleLogout}>
                <NavIcon name="logout" />Đăng xuất
              </button>
            </div>
          )}
        </div>
      </nav>
      <main className="app-main">{children}</main>
    </div>
  )
}
