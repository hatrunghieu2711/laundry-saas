import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { api } from '../lib/api'
import { formatVND } from '../lib/format'
import { formatPickupBoard, nowVnWall, startOfDayVn, addDaysVn, vnWallToISO } from '../lib/datetime'
import { ORDER_STATUS } from '../lib/orders'

// Tab "Lịch sử" (Stage 6.38; gộp Tra cứu cũ) — style mới. Ô tìm (mã/tên/SĐT, mọi đơn) +
// lọc nhanh Thời gian + Trạng thái + danh sách (mới nhất trước, phân trang). KHÔNG cần
// endpoint mới: GET /orders đã hỗ trợ from/to (created_at) + order_status[] + q + limit/offset.
const LIMIT = 25

// Thời gian → {from?, to?} ISO (created_at). Bỏ to = tới hiện tại.
function timeRange(key) {
  const now = nowVnWall()
  if (key === 'today') return { from: startOfDayVn(now) }
  if (key === 'yesterday')
    return { from: startOfDayVn(addDaysVn(now, -1)), to: startOfDayVn(now) }
  if (key === '7d') return { from: startOfDayVn(addDaysVn(now, -6)) }
  if (key === 'month') {
    const m = startOfDayVn(now)
    m.setUTCDate(1)
    return { from: m }
  }
  return {}
}
const TIME_FILTERS = [
  { key: 'today', label: 'Hôm nay' },
  { key: 'yesterday', label: 'Hôm qua' },
  { key: '7d', label: '7 ngày' },
  { key: 'month', label: 'Tháng này' },
]
// Trạng thái → order_status[]. 'all' = không lọc.
const STATUS_FILTERS = [
  { key: 'all', label: 'Tất cả', statuses: [] },
  { key: 'processing', label: 'Đang xử lý', statuses: ['created', 'washing', 'drying', 'ready'] },
  { key: 'delivered', label: 'Đã giao', statuses: ['delivered', 'completed'] },
  { key: 'cancelled', label: 'Đã hủy', statuses: ['cancelled'] },
]

function statusBadge(os) {
  if (os === 'cancelled') return { label: 'Đã hủy', cls: 'hbadge--cancel' }
  if (os === 'delivered' || os === 'completed')
    return { label: ORDER_STATUS[os] || 'Đã giao', cls: 'hbadge--done' }
  return { label: ORDER_STATUS[os] || os, cls: 'hbadge--proc' }
}

export default function History() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'
  const { branchId } = useBranch()

  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [timeKey, setTimeKey] = useState('7d')        // mặc định 7 ngày
  const [statusKey, setStatusKey] = useState('delivered') // mặc định Đã giao (đơn đã đóng; không lặp tab Đơn hàng)

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  // debounce search → q
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(t)
  }, [search])

  const searching = q !== ''

  const buildParams = useCallback(
    (off) => {
      const p = new URLSearchParams()
      if (isOwner && branchId) p.set('branch_id', branchId)
      if (searching) {
        // Đang tìm → ưu tiên kết quả khớp, BỎ QUA lọc thời gian/trạng thái (tìm mọi đơn).
        p.set('q', q)
      } else {
        const { from, to } = timeRange(timeKey)
        if (from) p.set('from', vnWallToISO(from))
        if (to) p.set('to', vnWallToISO(to))
        const st = STATUS_FILTERS.find((s) => s.key === statusKey)?.statuses || []
        st.forEach((s) => p.append('order_status', s))
      }
      p.set('limit', LIMIT)
      p.set('offset', off)
      return p
    },
    [isOwner, branchId, searching, q, timeKey, statusKey],
  )

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const d = await api.get(`/orders?${buildParams(0)}`)
      setItems(d.items)
      setTotal(d.total)
      setOffset(d.items.length)
    } catch (err) {
      setError(err?.message || 'Không tải được lịch sử')
    } finally {
      setLoading(false)
    }
  }, [buildParams])

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

  const countLabel = useMemo(() => (searching ? `${total} đơn khớp` : `${total} đơn`), [total, searching])

  return (
    <div className="history">
      <input
        className="input history__search"
        type="search"
        placeholder="Tìm mã đơn / tên / SĐT…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="Tìm đơn"
      />

      {/* Lọc nhanh (ẩn khi đang tìm — tìm ưu tiên toàn bộ) */}
      {!searching && (
        <>
          <div className="history__filters">
            {TIME_FILTERS.map((f) => (
              <button
                key={f.key}
                className={`chip chip--sm ${timeKey === f.key ? 'chip--active' : ''}`}
                onClick={() => setTimeKey(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="history__filters">
            {STATUS_FILTERS.map((f) => (
              <button
                key={f.key}
                className={`chip chip--sm ${statusKey === f.key ? 'chip--active' : ''}`}
                onClick={() => setStatusKey(f.key)}
              >
                {f.label}
              </button>
            ))}
          </div>
        </>
      )}
      {searching && <p className="history__hint">Đang tìm — bỏ qua bộ lọc thời gian/trạng thái.</p>}

      {error && <div className="alert alert--error">{error}</div>}

      <div className="history__count">{loading && items.length === 0 ? 'Đang tải…' : countLabel}</div>

      {!loading && items.length === 0 && !error && (
        <p className="history__hint">Không có đơn nào.</p>
      )}

      <div className="history__list">
        {items.map((o) => {
          const sb = statusBadge(o.order_status)
          return (
            <button key={o.id} className="history__row" onClick={() => navigate(`/orders/${o.id}`)}>
              <div className="history__r1">
                <span className="history__code">{o.order_code}</span>
                <span className="history__amount">{formatVND(o.total_amount)}</span>
              </div>
              <div className="history__r2">
                <span className="history__cust">{o.customer_name || 'Khách lẻ'}</span>
                <span className={`hbadge ${sb.cls}`}>{sb.label}</span>
                <span className="history__time">{formatPickupBoard(o.created_at)}</span>
              </div>
            </button>
          )
        })}
      </div>

      {items.length > 0 && items.length < total && (
        <button className="btn btn--ghost btn--block" onClick={loadMore} disabled={loading}>
          {loading ? 'Đang tải…' : `Tải thêm (${items.length}/${total})`}
        </button>
      )}
    </div>
  )
}
