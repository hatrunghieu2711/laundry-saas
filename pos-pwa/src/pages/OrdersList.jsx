import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { formatDateTime, formatVND } from '../lib/format'
import { ORDER_STATUS, PAYMENT_STATUS, STATUS_FILTERS } from '../lib/orders'

const LIMIT = 20
const PAY_FILTERS = [
  { key: null, label: 'Tất cả' },
  { key: 'unpaid', label: 'Chưa thu' },
  { key: 'partial', label: 'Một phần' },
  { key: 'paid', label: 'Đã thu' },
  { key: 'debt', label: 'Nợ' },
]

export default function OrdersList() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(isOwner ? null : user?.branch_id || null)
  const [statusKey, setStatusKey] = useState('active')
  const [payKey, setPayKey] = useState(null)
  const [search, setSearch] = useState('')
  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    if (!isOwner) return
    api
      .get('/branches?limit=200')
      .then((p) => {
        const active = p.items.filter((b) => b.status === 'active')
        setBranches(active)
        if (active.length === 1) setBranchId(active[0].id)
      })
      .catch(() => {})
  }, [isOwner])

  const buildQuery = useCallback(
    (off) => {
      const p = new URLSearchParams()
      p.set('limit', LIMIT)
      p.set('offset', off)
      if (isOwner && branchId) p.set('branch_id', branchId)
      const sf = STATUS_FILTERS.find((s) => s.key === statusKey)
      if (sf) sf.statuses.forEach((s) => p.append('order_status', s))
      if (payKey) p.append('payment_status', payKey)
      return p.toString()
    },
    [isOwner, branchId, statusKey, payKey],
  )

  const reload = useCallback(async () => {
    if (isOwner && !branchId) {
      setItems([])
      setTotal(0)
      setOffset(0)
      return
    }
    setLoading(true)
    setError('')
    try {
      const d = await api.get(`/orders?${buildQuery(0)}`)
      setItems(d.items)
      setTotal(d.total)
      setOffset(d.items.length)
    } catch (err) {
      setError(err?.message || 'Không tải được danh sách đơn')
    } finally {
      setLoading(false)
    }
  }, [isOwner, branchId, buildQuery])

  useEffect(() => {
    if (!search) reload()
  }, [reload, search])

  const loadMore = async () => {
    setLoading(true)
    try {
      const d = await api.get(`/orders?${buildQuery(offset)}`)
      setItems((p) => [...p, ...d.items])
      setOffset((o) => o + d.items.length)
    } catch (err) {
      setError(err?.message || '')
    } finally {
      setLoading(false)
    }
  }

  const doSearch = async (e) => {
    e?.preventDefault()
    const code = search.trim()
    if (!code) {
      reload()
      return
    }
    setLoading(true)
    setError('')
    try {
      const o = await api.get(`/orders/code/${encodeURIComponent(code)}`)
      setItems([o])
      setTotal(1)
      setOffset(1)
    } catch (err) {
      if (err?.status === 404) {
        setItems([])
        setTotal(0)
      } else setError(err?.message || '')
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="orders">
      {isOwner && (
        <div className="branch-picker">
          <div className="branch-picker__chips">
            {branches.map((b) => (
              <button
                key={b.id}
                className={`chip ${branchId === b.id ? 'chip--active' : ''}`}
                onClick={() => setBranchId(b.id)}
              >
                {b.code} · {b.name}
              </button>
            ))}
          </div>
        </div>
      )}

      <form className="orders__search" onSubmit={doSearch}>
        <input
          className="input"
          type="text"
          placeholder="Tìm mã đơn (B1-00001)"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <button type="submit" className="btn btn--ghost btn--sm">
          Tìm
        </button>
      </form>

      <div className="chip-row">
        {STATUS_FILTERS.map((s) => (
          <button
            key={s.key}
            className={`chip chip--sm ${statusKey === s.key ? 'chip--active' : ''}`}
            onClick={() => setStatusKey(s.key)}
          >
            {s.label}
          </button>
        ))}
      </div>
      <div className="chip-row">
        {PAY_FILTERS.map((p) => (
          <button
            key={p.key || 'all'}
            className={`chip chip--sm ${payKey === p.key ? 'chip--active' : ''}`}
            onClick={() => setPayKey(p.key)}
          >
            {p.label}
          </button>
        ))}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {items.length === 0 && !loading && <p className="shift__hint">Không có đơn nào.</p>}

      <div className="order-list">
        {items.map((o) => {
          const ps = PAYMENT_STATUS[o.payment_status] || { label: o.payment_status, cls: '' }
          return (
            <button key={o.id} className="order-row" onClick={() => navigate(`/orders/${o.id}`)}>
              <div className="order-row__top">
                <span className="order-row__code">{o.order_code}</span>
                <span className="order-row__amount">{formatVND(o.total_amount)}</span>
              </div>
              <div className="order-row__mid">
                <span className={`badge-ps ${ps.cls}`}>{ps.label}</span>
                <span className="order-row__os">{ORDER_STATUS[o.order_status] || o.order_status}</span>
              </div>
              <div className="order-row__bot">
                <span>{o.customer_name || 'Khách lẻ'}</span>
                <span>{formatDateTime(o.created_at)}</span>
              </div>
            </button>
          )
        })}
      </div>

      {!search && items.length < total && (
        <button className="btn btn--ghost btn--block" onClick={loadMore} disabled={loading}>
          {loading ? 'Đang tải…' : `Tải thêm (${items.length}/${total})`}
        </button>
      )}
    </div>
  )
}
