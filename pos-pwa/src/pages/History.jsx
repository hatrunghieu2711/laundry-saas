import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Receipt from '../components/Receipt'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { api } from '../lib/api'
import { formatVND } from '../lib/format'
import { formatPickupBoard, nowVnWall, startOfDayVn, addDaysVn, vnWallToISO } from '../lib/datetime'
import { ORDER_STATUS } from '../lib/orders'

// Tab "Lịch sử" (Stage 6.38 → hàng mở rộng + timeline 6.41). GET /orders (list) đủ info cơ
// bản (items/payment/phone); mở 1 hàng → lazy GET /orders/{id} (kèm tracking) dựng timeline.
const LIMIT = 25
const PAY_SUB = { paid: 'đã thu', debt: 'nợ', partial: 'thu 1 phần', unpaid: 'chưa thu', refunded: 'đã hoàn' }

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

function statusBadge(os) {
  if (os === 'cancelled') return { label: ORDER_STATUS[os] || 'Đã hủy', cls: 'hbadge--cancel' }
  if (os === 'delivered' || os === 'completed')
    return { label: ORDER_STATUS[os] || 'Đã giao', cls: 'hbadge--done' }
  if (os === 'created') return { label: ORDER_STATUS[os] || 'Mới tạo', cls: 'hbadge--new' }
  return { label: ORDER_STATUS[os] || os, cls: 'hbadge--proc' }
}

// 4 mốc timeline từ tracking [{status, at}] (asc). washing|drying SỚM NHẤT = "Đang xử lý";
// cancelled → bước cuối thành "Đã hủy" (đỏ) + giờ hủy.
function buildTimeline(order) {
  const m = {}
  for (const e of order.tracking || []) {
    if (e.status === 'created' && !m.created) m.created = e.at
    if ((e.status === 'washing' || e.status === 'drying') && !m.proc) m.proc = e.at
    if (e.status === 'ready' && !m.ready) m.ready = e.at
    if (e.status === 'delivered' && !m.delivered) m.delivered = e.at
    if (e.status === 'cancelled') m.cancelled = e.at
  }
  const steps = [
    { label: 'Nhận đơn', at: m.created, sub: PAY_SUB[order.payment_status] },
    { label: 'Đang xử lý', at: m.proc },
    { label: 'Sẵn sàng', at: m.ready },
  ]
  steps.push(
    m.cancelled
      ? { label: 'Đã hủy', at: m.cancelled, danger: true }
      : { label: 'Đã giao', at: m.delivered },
  )
  return steps
}

function Chevron({ open }) {
  return (
    <svg
      className={`history__chev ${open ? 'is-open' : ''}`}
      viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2"
      strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
    >
      <path d="M6 9l6 6 6-6" />
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
  const [timeKey, setTimeKey] = useState('7d')
  const [statusKey, setStatusKey] = useState('delivered')

  const [items, setItems] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState('')

  const [openId, setOpenId] = useState(null)   // 1 đơn mở/lần
  const [details, setDetails] = useState({})   // {id: {loading, order, error}} — lazy cache

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
    setOpenId(null) // đổi lọc → thu hàng đang mở
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

  useEffect(() => { load() }, [load])

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

  // Mở/đóng 1 hàng — lazy GET /orders/{id} (kèm tracking) khi mở lần đầu.
  const toggle = (id) => {
    if (openId === id) { setOpenId(null); return }
    setOpenId(id)
    if (!details[id]?.order) {
      setDetails((d) => ({ ...d, [id]: { loading: true } }))
      api.get(`/orders/${id}`)
        .then((o) => setDetails((d) => ({ ...d, [id]: { order: o } })))
        .catch((err) => setDetails((d) => ({ ...d, [id]: { error: err?.message || 'Không tải được' } })))
    }
  }

  const countLabel = useMemo(
    () => (searching ? `${total} đơn khớp` : `${total} đơn`),
    [total, searching],
  )
  const openOrder = openId ? details[openId]?.order : null

  return (
    <div className="history">
      <div className="history__bar">
        <input
          className="input history__search"
          type="search"
          placeholder="Tìm mã đơn / tên / SĐT…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          aria-label="Tìm đơn"
        />
        <select className="input history__sel" value={statusKey} onChange={(e) => setStatusKey(e.target.value)} aria-label="Lọc trạng thái">
          {STATUS_FILTERS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
        <select className="input history__sel" value={timeKey} onChange={(e) => setTimeKey(e.target.value)} aria-label="Lọc thời gian">
          {TIME_FILTERS.map((f) => <option key={f.key} value={f.key}>{f.label}</option>)}
        </select>
      </div>

      {error && <div className="alert alert--error">{error}</div>}
      <div className="history__count">{loading && items.length === 0 ? 'Đang tải…' : countLabel}</div>
      {!loading && items.length === 0 && !error && <p className="history__hint">Không có đơn nào.</p>}

      {items.length > 0 && (
        <div className="history__list">
          {items.map((o) => {
            const sb = statusBadge(o.order_status)
            const open = openId === o.id
            const det = details[o.id]
            return (
              <div className="history__item" key={o.id}>
                <button
                  className="history__row"
                  onClick={() => toggle(o.id)}
                  aria-expanded={open}
                  aria-label={`Đơn ${o.order_code}`}
                >
                  <span className="history__code">{o.order_code}</span>
                  <span className="history__cust">{o.customer_name || 'Khách lẻ'}</span>
                  <span className={`hbadge ${sb.cls}`}>{sb.label}</span>
                  <span className="history__time">{formatPickupBoard(o.created_at)}</span>
                  <span className="history__amount">{formatVND(o.total_amount)}</span>
                  <span className="history__menu"><Chevron open={open} /></span>
                </button>

                {open && (
                  <div className="history__exp">
                    {det?.loading && <p className="history__hint">Đang tải chi tiết…</p>}
                    {det?.error && <div className="alert alert--error">{det.error}</div>}
                    {det?.order && (
                      <>
                        <div className="hexp__info">
                          <div className="hexp__cell">
                            <span className="hexp__lbl">Khách</span>
                            <span>
                              {det.order.customer_name || 'Khách lẻ'}
                              {det.order.customer_phone ? ` · ${det.order.customer_phone}` : ''}
                            </span>
                          </div>
                          <div className="hexp__cell">
                            <span className="hexp__lbl">Dịch vụ</span>
                            <span>
                              {(det.order.items || [])
                                .map((it) => `${it.service_name} ×${Number(it.quantity)}`)
                                .join(', ') || '—'}
                            </span>
                          </div>
                          <div className="hexp__cell">
                            <span className="hexp__lbl">Thanh toán</span>
                            <span>{PAY_SUB[det.order.payment_status] || det.order.payment_status} · {formatVND(det.order.total_amount)}</span>
                          </div>
                        </div>

                        {/* Timeline ngang 4 bước */}
                        <div className="htl">
                          {buildTimeline(det.order).map((s, i, arr) => (
                            <Fragment key={s.label}>
                              <div className={`htl__step ${s.at ? 'is-done' : 'is-todo'} ${s.danger ? 'is-cancel' : ''}`}>
                                <span className="htl__time">{s.at ? formatPickupBoard(s.at) : '—'}</span>
                                <span className="htl__dot" />
                                <span className="htl__name">{s.label}{s.sub ? ` (${s.sub})` : ''}</span>
                              </div>
                              {i < arr.length - 1 && <span className="htl__sep">›</span>}
                            </Fragment>
                          ))}
                        </div>

                        <div className="hexp__acts">
                          <button className="btn btn--ghost btn--sm" onClick={() => window.print()}>In lại bill</button>
                          <button className="btn btn--ghost btn--sm" onClick={() => navigate(`/orders/${o.id}`)}>Xem chi tiết đầy đủ</button>
                        </div>
                      </>
                    )}
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {items.length > 0 && items.length < total && (
        <button className="btn btn--ghost btn--block" onClick={loadMore} disabled={loading}>
          {loading ? 'Đang tải…' : `Tải thêm (${items.length}/${total})`}
        </button>
      )}

      {/* Bill ẩn (in lại) — chỉ render đơn đang mở; @media print hiện .print-receipt, ẩn #root. */}
      {openOrder && <Receipt order={openOrder} />}
    </div>
  )
}
