import { useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { api } from '../lib/api'
import { formatVND } from '../lib/format'
import { formatPickupBoard, nowVnWall, startOfDayVn, addDaysVn, vnWallToISO } from '../lib/datetime'
import { ORDER_STATUS } from '../lib/orders'

// Tab "Lịch sử" (Stage 6.38; 1-hàng-lọc + danh sách kẻ dòng nén 6.40). KHÔNG cần endpoint
// mới: GET /orders đã hỗ trợ from/to (created_at) + order_status[] + q + limit/offset.
// OrderDetail là TRANG riêng (useParams + print + pay/cancel) → bấm dòng ĐIỀU HƯỚNG sang
// /orders/:id (KHÔNG popup — tránh nửa vời). Icon ☰ là dấu hiệu trực quan.
const LIMIT = 25

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
// Mặc định nằm ĐẦU mỗi danh sách (option đầu của select).
const TIME_FILTERS = [
  { key: '7d', label: '7 ngày' },
  { key: 'today', label: 'Hôm nay' },
  { key: 'yesterday', label: 'Hôm qua' },
  { key: 'month', label: 'Tháng này' },
]
const STATUS_FILTERS = [
  { key: 'delivered', label: 'Đã giao', statuses: ['delivered', 'completed'] },
  { key: 'all', label: 'Tất cả', statuses: [] },
  { key: 'processing', label: 'Đang xử lý', statuses: ['created', 'washing', 'drying', 'ready'] },
  { key: 'cancelled', label: 'Đã hủy', statuses: ['cancelled'] },
]

// Badge màu: đã giao xanh / đã hủy đỏ / mới tạo amber / đang xử lý cam.
function statusBadge(os) {
  if (os === 'cancelled') return { label: ORDER_STATUS[os] || 'Đã hủy', cls: 'hbadge--cancel' }
  if (os === 'delivered' || os === 'completed')
    return { label: ORDER_STATUS[os] || 'Đã giao', cls: 'hbadge--done' }
  if (os === 'created') return { label: ORDER_STATUS[os] || 'Mới tạo', cls: 'hbadge--new' }
  return { label: ORDER_STATUS[os] || os, cls: 'hbadge--proc' } // washing/drying/ready
}

// ☰ inline SVG (Chrome 56 / PWA offline — KHÔNG webfont). Cùng path với Board.
function MenuIcon() {
  return (
    <svg
      className="history__menu-svg"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d="M4 6h16 M4 12h16 M4 18h16" />
    </svg>
  )
}

export default function History() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'
  const { branchId } = useBranch()

  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [timeKey, setTimeKey] = useState('7d')            // mặc định 7 ngày
  const [statusKey, setStatusKey] = useState('delivered') // mặc định Đã giao

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

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
        // Đang tìm → ưu tiên kết quả khớp, BỎ QUA lọc thời gian/trạng thái.
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

  const countLabel = useMemo(
    () => (searching ? `${total} đơn khớp` : `${total} đơn`),
    [total, searching],
  )

  return (
    <div className="history">
      {/* 1 hàng: ô tìm (rộng) + dropdown trạng thái + dropdown ngày */}
      <div className="history__bar">
        <input
          className="input history__search"
          type="search"
          placeholder="Tìm mã đơn / tên / SĐT…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Tìm đơn"
        />
        <select
          className="input history__sel"
          value={statusKey}
          onChange={(e) => setStatusKey(e.target.value)}
          aria-label="Lọc trạng thái"
        >
          {STATUS_FILTERS.map((f) => (
            <option key={f.key} value={f.key}>{f.label}</option>
          ))}
        </select>
        <select
          className="input history__sel"
          value={timeKey}
          onChange={(e) => setTimeKey(e.target.value)}
          aria-label="Lọc thời gian"
        >
          {TIME_FILTERS.map((f) => (
            <option key={f.key} value={f.key}>{f.label}</option>
          ))}
        </select>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      <div className="history__count">
        {loading && items.length === 0 ? 'Đang tải…' : countLabel}
      </div>

      {!loading && items.length === 0 && !error && (
        <p className="history__hint">Không có đơn nào.</p>
      )}

      {items.length > 0 && (
        <div className="history__list">
          {items.map((o) => {
            const sb = statusBadge(o.order_status)
            return (
              <button
                key={o.id}
                className="history__row"
                onClick={() => navigate(`/orders/${o.id}`)}
                aria-label={`Chi tiết đơn ${o.order_code}`}
              >
                <span className="history__code">{o.order_code}</span>
                <span className="history__cust">{o.customer_name || 'Khách lẻ'}</span>
                <span className={`hbadge ${sb.cls}`}>{sb.label}</span>
                <span className="history__time">{formatPickupBoard(o.created_at)}</span>
                <span className="history__amount">{formatVND(o.total_amount)}</span>
                <span className="history__menu" aria-hidden="true"><MenuIcon /></span>
              </button>
            )
          })}
        </div>
      )}

      {items.length > 0 && items.length < total && (
        <button className="btn btn--ghost btn--block" onClick={loadMore} disabled={loading}>
          {loading ? 'Đang tải…' : `Tải thêm (${items.length}/${total})`}
        </button>
      )}
    </div>
  )
}
