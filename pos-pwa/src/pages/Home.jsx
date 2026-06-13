import { useAuth } from '../context/AuthContext'

// Trang chủ POS (placeholder Stage 3a). Các thao tác sẽ nối ở phase sau.
const ACTIONS = [
  { key: 'shift', label: 'Mở / Đóng ca', icon: '🕒', roles: ['owner', 'manager', 'staff'] },
  { key: 'order', label: 'Tạo đơn', icon: '🧺', roles: ['owner', 'manager', 'staff'] },
  { key: 'pay', label: 'Thu tiền', icon: '💵', roles: ['owner', 'manager', 'staff'] },
  { key: 'status', label: 'Đổi trạng thái', icon: '🔄', roles: ['owner', 'manager', 'staff'] },
]

export default function Home() {
  const { user } = useAuth()
  const actions = ACTIONS.filter((a) => a.roles.includes(user?.role))

  return (
    <div className="home">
      <h2 className="home__greeting">Xin chào, {user?.full_name} 👋</h2>
      <p className="home__hint">Chọn thao tác để bắt đầu.</p>

      <div className="grid-actions">
        {actions.map((a) => (
          <button key={a.key} className="action-card" disabled title="Sắp có ở phase sau">
            <span className="action-card__icon">{a.icon}</span>
            <span className="action-card__label">{a.label}</span>
            <span className="action-card__soon">Sắp có</span>
          </button>
        ))}
      </div>
    </div>
  )
}
