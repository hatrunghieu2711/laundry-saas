import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'

// Badge hạn (khớp expiry_status BE): warning vàng · grace cam · expired đỏ.
const EXPIRY_BADGE = {
  warning: { label: 'Sắp hết hạn', bg: '#fef9c3', color: '#854d0e' },
  grace: { label: 'Ân hạn', bg: '#ffedd5', color: '#9a3412' },
  expired: { label: 'Đã hết hạn', bg: '#fde8e8', color: '#b42318' },
}
const STATUS_LABEL = { active: 'Hoạt động', suspended: 'Tạm ngưng', inactive: 'Ngưng' }

function Stat({ label, value }) {
  return (
    <div style={{ border: '1px solid var(--line)', borderRadius: 8, padding: '12px 14px', flex: '1 1 120px', minWidth: 120 }}>
      <div style={{ fontSize: 24, fontWeight: 700, lineHeight: 1.1 }}>{value}</div>
      <div className="shift__hint">{label}</div>
    </div>
  )
}

// Dashboard tổng quan Super Admin — CHỈ ĐỌC. Số liệu từ GET /admin/dashboard.
export default function AdminDashboard() {
  const navigate = useNavigate()
  const [data, setData] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setData(await api.admin.dashboard())
    } catch (e) {
      setError(e?.message || 'Không tải được tổng quan')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  if (loading) return <p className="shift__hint">Đang tải…</p>
  if (error) return <div className="alert alert--error">{error}</div>
  if (!data) return null

  const totalTenants = Object.values(data.tenants_by_status).reduce((a, b) => a + b, 0)

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Tổng quan</h2>
        <button className="btn btn--ghost btn--sm" onClick={load}>Làm mới</button>
      </div>

      {/* Thẻ số liệu */}
      <div style={{ display: 'flex', flexWrap: 'wrap', gap: 10, marginTop: 8 }}>
        <Stat label="Cửa hàng" value={totalTenants} />
        <Stat label="Đơn hôm nay" value={data.orders_today} />
        <Stat label="Đơn tháng này" value={data.orders_month} />
        <Stat label="Chi nhánh đang dùng" value={data.branches_active} />
        <Stat label="Nhân viên" value={data.users_active} />
      </div>

      {/* Tenant theo trạng thái */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Cửa hàng theo trạng thái</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 12 }}>
          {Object.entries(data.tenants_by_status).map(([st, n]) => (
            <span key={st} className="shift__hint">{STATUS_LABEL[st] || st}: <strong>{n}</strong></span>
          ))}
        </div>
      </div>

      {/* Cần chú ý (hạn gói) */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Cần chú ý ({data.expiring.length})</div>
        {data.expiring.length === 0 ? (
          <p className="shift__hint">Không có cửa hàng nào sắp/đã hết hạn.</p>
        ) : (
          <div className="cat-group">
            {data.expiring.map((e) => {
              const b = EXPIRY_BADGE[e.expiry_status] || EXPIRY_BADGE.warning
              return (
                <div className="cat-item" key={e.tenant_id}>
                  <div className="cat-item__main">
                    <div className="cat-item__name">
                      {e.name}
                      <span style={{ marginLeft: 6, fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 999, background: b.bg, color: b.color }}>
                        {b.label}{e.days_left != null ? ` · ${e.days_left}n` : ''}
                      </span>
                    </div>
                    <div className="cat-item__meta">{e.slug} · hết hạn {e.expires_at.slice(0, 10)}</div>
                  </div>
                  <button className="btn btn--ghost btn--sm" onClick={() => navigate(`/admin/tenants/${e.tenant_id}`)}>Chi tiết</button>
                </div>
              )
            })}
          </div>
        )}
      </div>

      {/* Mới tạo gần đây */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Mới tạo gần đây</div>
        {data.recent_tenants.length === 0 ? (
          <p className="shift__hint">Chưa có cửa hàng nào.</p>
        ) : (
          <div className="cat-group">
            {data.recent_tenants.map((t) => (
              <div className="cat-item" key={t.id}>
                <div className="cat-item__main">
                  <div className="cat-item__name">{t.name}</div>
                  <div className="cat-item__meta">{t.slug} · {formatDateTime(t.created_at)}</div>
                </div>
                <button className="btn btn--ghost btn--sm" onClick={() => navigate(`/admin/tenants/${t.id}`)}>Chi tiết</button>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
