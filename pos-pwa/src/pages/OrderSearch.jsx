import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { api } from '../lib/api'
import { formatDateTime, formatVND } from '../lib/format'
import { ORDER_STATUS, PAYMENT_STATUS } from '../lib/orders'

// Tab "Tra cứu" (Stage 6.11): tìm MỌI đơn (mọi trạng thái, mọi ngày) theo mã đơn /
// tên khách / SĐT — 1 ô search, backend match cả 3 trường (GET /orders?q=). Có phân
// trang (limit/offset) — KHÔNG tải hết DB. Lọc theo tenant + chi nhánh đang chọn.
const PAY_FILTERS = [
  { key: null, label: 'Mọi TT' },
  { key: 'unpaid', label: 'Chưa thu' },
  { key: 'paid', label: 'Đã thu' },
  { key: 'debt', label: 'Nợ' },
]
const STATUS_OPTIONS = [
  'created', 'washing', 'drying', 'ready', 'delivered', 'completed', 'cancelled',
]
const LIMIT = 25

export default function OrderSearch() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'
  const { branchId } = useBranch()

  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [payKey, setPayKey] = useState(null)
  const [statusKey, setStatusKey] = useState('') // '' = mọi trạng thái

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')
  const [searched, setSearched] = useState(false)

  // debounce search → q
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(t)
  }, [search])

  // Chỉ tra khi có từ khoá HOẶC có bộ lọc → tránh "tải hết DB".
  const active = q !== '' || payKey != null || statusKey !== ''

  const buildParams = useCallback(
    (off) => {
      const p = new URLSearchParams()
      if (isOwner && branchId) p.set('branch_id', branchId)
      if (q) p.set('q', q)
      if (payKey) p.set('payment_status', payKey)
      if (statusKey) p.set('order_status', statusKey)
      p.set('limit', LIMIT)
      p.set('offset', off)
      return p
    },
    [isOwner, branchId, q, payKey, statusKey],
  )

  const load = useCallback(async () => {
    if (!active) {
      setItems([])
      setTotal(0)
      setSearched(false)
      return
    }
    setLoading(true)
    setError('')
    try {
      const d = await api.get(`/orders?${buildParams(0)}`)
      setItems(d.items)
      setTotal(d.total)
      setOffset(d.items.length)
      setSearched(true)
    } catch (err) {
      setError(err?.message || 'Không tra cứu được')
    } finally {
      setLoading(false)
    }
  }, [active, buildParams])

  useEffect(() => {
    load()
  }, [load])

  const loadMore = async () => {
    setLoading(true)
    try {
      const d = await api.get(`/orders?${buildParams(offset)}`)
      setItems((prev) => [...prev, ...d.items])
      setOffset((o) => o + d.items.length)
    } catch (err) {
      setError(err?.message || '')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="tra">
      <input
        className="tra__search"
        type="search"
        placeholder="🔍 Nhập SĐT / tên khách / mã đơn…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="Tra cứu đơn"
        autoFocus
      />

      <div className="tra__filters">
        {PAY_FILTERS.map((f) => (
          <button
            key={f.key || 'all'}
            className={`chip chip--sm ${payKey === f.key ? 'chip--active' : ''}`}
            onClick={() => setPayKey(f.key)}
          >
            {f.label}
          </button>
        ))}
        <select
          className="tra__status"
          value={statusKey}
          onChange={(e) => setStatusKey(e.target.value)}
          aria-label="Lọc trạng thái"
        >
          <option value="">Mọi trạng thái</option>
          {STATUS_OPTIONS.map((s) => (
            <option key={s} value={s}>
              {ORDER_STATUS[s]}
            </option>
          ))}
        </select>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {!active && (
        <p className="tra__hint">Nhập số điện thoại, tên khách hoặc mã đơn để tra cứu mọi đơn.</p>
      )}
      {active && searched && items.length === 0 && !loading && (
        <p className="tra__hint">Không tìm thấy đơn nào khớp.</p>
      )}

      {items.length > 0 && (
        <>
          <div className="tra__count">{total} đơn khớp</div>
          <div className="tra__list">
            {items.map((o) => {
              const ps = PAYMENT_STATUS[o.payment_status] || { label: o.payment_status, cls: '' }
              return (
                <button key={o.id} className="tra__row" onClick={() => navigate(`/orders/${o.id}`)}>
                  <div className="tra__row-top">
                    <span className="tra__code">{o.order_code}</span>
                    <span className="tra__amount">{formatVND(o.total_amount)}</span>
                  </div>
                  <div className="tra__row-mid">
                    <span className={`badge-ps badge-ps--xs ${ps.cls}`}>{ps.label}</span>
                    <span className="tra__os">{ORDER_STATUS[o.order_status] || o.order_status}</span>
                  </div>
                  <div className="tra__row-cust">
                    {o.customer_name || 'Khách lẻ'}
                    {o.customer_phone ? ` · ${o.customer_phone}` : ''}
                  </div>
                  <div className="tra__row-dates">
                    <span>Tạo: {formatDateTime(o.created_at)}</span>
                    <span>Giao: {formatDateTime(o.pickup_at)}</span>
                  </div>
                </button>
              )
            })}
          </div>
          {items.length < total && (
            <button className="btn btn--ghost btn--block" onClick={loadMore} disabled={loading}>
              {loading ? 'Đang tải…' : `Tải thêm (${items.length}/${total})`}
            </button>
          )}
        </>
      )}
    </div>
  )
}
