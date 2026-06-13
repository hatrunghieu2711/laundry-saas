import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { formatVND } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'

// Bảng đơn (dashboard vận hành): Kanban theo order_status, tự refresh.
const COLUMNS = [
  { key: 'created', label: 'Mới nhận' },
  { key: 'washing', label: 'Đang giặt' },
  { key: 'drying', label: 'Đang sấy' },
  { key: 'ready', label: 'Sẵn sàng' },
  { key: 'delivered', label: 'Đã giao' },
]
// Viền trái thẻ theo payment_status.
const BORDER = {
  unpaid: 'bl--unpaid',
  partial: 'bl--partial',
  paid: 'bl--paid',
  debt: 'bl--debt',
  refunded: 'bl--refunded',
}
const REFRESH_MS = 30000

export default function Board() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(null) // owner: null = tất cả chi nhánh
  const [data, setData] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)

  useEffect(() => {
    if (!isOwner) return
    api
      .get('/branches?limit=200')
      .then((p) => setBranches(p.items.filter((b) => b.status === 'active')))
      .catch(() => {})
  }, [isOwner])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const q = isOwner && branchId ? `?branch_id=${branchId}` : ''
      const d = await api.get(`/orders/board${q}`)
      setData(d)
      setUpdatedAt(new Date())
    } catch (err) {
      setError(err?.message || 'Không tải được bảng đơn')
    } finally {
      setLoading(false)
    }
  }, [isOwner, branchId])

  useEffect(() => {
    load()
  }, [load])

  // Tự refresh định kỳ để bảng phản ánh trạng thái mới.
  useEffect(() => {
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  const s = data?.summary
  const cols = data?.columns || {}

  return (
    <div className="board">
      {isOwner && branches.length > 0 && (
        <div className="branch-picker">
          <div className="branch-picker__chips">
            <button
              className={`chip chip--sm ${!branchId ? 'chip--active' : ''}`}
              onClick={() => setBranchId(null)}
            >
              Tất cả CN
            </button>
            {branches.map((b) => (
              <button
                key={b.id}
                className={`chip chip--sm ${branchId === b.id ? 'chip--active' : ''}`}
                onClick={() => setBranchId(b.id)}
              >
                {b.code} · {b.name}
              </button>
            ))}
          </div>
        </div>
      )}

      {/* Thanh tổng */}
      {s && (
        <div className="board__bar">
          <div className="board__stat">
            <span className="board__stat-num">{s.total_orders}</span>
            <span className="board__stat-lbl">Ở tiệm</span>
          </div>
          <div className="board__stat board__stat--unpaid">
            <span className="board__stat-num">{s.unpaid}</span>
            <span className="board__stat-lbl">Chưa thu</span>
          </div>
          <div className="board__stat board__stat--paid">
            <span className="board__stat-num">{s.paid}</span>
            <span className="board__stat-lbl">Đã thu</span>
          </div>
          <div className="board__stat board__stat--debt">
            <span className="board__stat-num">{s.debt}</span>
            <span className="board__stat-lbl">Nợ</span>
          </div>
          <div className="board__stat board__stat--overdue">
            <span className="board__stat-num">{s.overdue}</span>
            <span className="board__stat-lbl">Trễ hẹn</span>
          </div>
        </div>
      )}

      <div className="board__toolbar">
        <button className="btn btn--ghost btn--sm" onClick={load} disabled={loading}>
          {loading ? 'Đang tải…' : '↻ Làm mới'}
        </button>
        {updatedAt && (
          <span className="board__updated">
            Cập nhật {String(updatedAt.getHours()).padStart(2, '0')}:
            {String(updatedAt.getMinutes()).padStart(2, '0')}
          </span>
        )}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {data && (
        <div className="board__cols">
          {COLUMNS.map((col) => {
            const list = cols[col.key] || []
            return (
              <section className="board__col" key={col.key}>
                <div className="board__col-head">
                  <span>{col.label}</span>
                  <span className="board__col-count">{list.length}</span>
                </div>
                <div className="board__col-body">
                  {list.length === 0 ? (
                    <p className="board__empty">—</p>
                  ) : (
                    list.map((o) => (
                      <button
                        key={o.id}
                        className={`board__card ${BORDER[o.payment_status] || ''}`}
                        onClick={() => navigate(`/orders/${o.id}`)}
                      >
                        <div className="board__card-top">
                          <span className="board__card-code">{o.order_code}</span>
                          {o.is_overdue && <span className="board__overdue">TRỄ</span>}
                        </div>
                        <div className="board__card-cust">{o.customer_name || 'Khách lẻ'}</div>
                        <div className="board__card-bot">
                          <span className="board__card-total">{formatVND(o.total_amount)}</span>
                          <span className={`board__card-pickup ${o.is_overdue ? 'is-overdue' : ''}`}>
                            🕒 {formatPickupShort(o.pickup_at)}
                          </span>
                        </div>
                      </button>
                    ))
                  )}
                </div>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}
