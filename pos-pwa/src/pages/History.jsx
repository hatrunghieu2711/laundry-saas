import { Fragment, useCallback, useEffect, useMemo, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import Receipt from '../components/Receipt'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { api } from '../lib/api'
import { formatVND } from '../lib/format'
import { formatPickupBoard, nowVnWall, startOfDayVn, addDaysVn, vnWallToISO } from '../lib/datetime'
import { ORDER_STATUS } from '../lib/orders'
import { buildTimeline } from '../lib/timeline'

// Tab "Lịch sử" (Stage 6.38 → hàng mở rộng + timeline 6.41). GET /orders (list) đủ info cơ
// bản (items/payment/phone); mở 1 hàng → lazy GET /orders/{id} (kèm tracking) dựng timeline.
const LIMIT = 25
const PAY_LABEL = { paid: 'Đã thu', debt: 'Còn nợ', partial: 'Thu một phần', unpaid: 'Chưa thu', refunded: 'Đã hoàn' }

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
  const [statusKey, setStatusKey] = useState('all')
  const [sortKey, setSortKey] = useState('updated_at') // mặc định: mới cập nhật

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
      // updated_at = xếp theo lần CHẠM gần nhất (đổi trạng thái/thu tiền/sửa); created_at = mới tạo.
      p.set('sort', sortKey)
      p.set('limit', LIMIT)
      p.set('offset', off)
      return p
    },
    [isOwner, branchId, searching, q, timeKey, statusKey, sortKey],
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
      <div className="history__count">
        <span className="history__count-n">{loading && items.length === 0 ? 'Đang tải…' : countLabel}</span>
        <span className="history__sort">
          <span className="history__sort-lbl">Sắp xếp:</span>
          <button
            className={`history__sortbtn ${sortKey === 'updated_at' ? 'chip--active' : ''}`}
            onClick={() => setSortKey('updated_at')}
          >Mới cập nhật</button>
          <button
            className={`history__sortbtn ${sortKey === 'created_at' ? 'chip--active' : ''}`}
            onClick={() => setSortKey('created_at')}
          >Mới tạo</button>
        </span>
      </div>
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
                    {det?.order && (() => {
                      const od = det.order
                      const ps = od.payment_status
                      const payTone = ps === 'paid' ? 'is-ok' : ps === 'refunded' ? '' : 'is-due'
                      const note = (od.notes || '').trim()
                      return (
                        <>
                          {/* HÀNG 1: 5 cột ngang (Ghi chú ẩn nếu trống), ngăn bằng border-left. */}
                          <div className="hexp__cols">
                            <div className="hexp__col hexp__col--cust">
                              <span className="hexp__lbl">Khách hàng</span>
                              <span className="hexp__name">{od.customer_name || 'Khách lẻ'}</span>
                              {od.customer_phone && <span className="hexp__phone">{od.customer_phone}</span>}
                            </div>
                            <div className="hexp__col hexp__col--svc">
                              <span className="hexp__lbl">Dịch vụ</span>
                              {(od.items || []).map((it) => (
                                <span className="hexp__svc" key={it.id}>{it.service_name} ×{Number(it.quantity)}</span>
                              ))}
                              {(!od.items || od.items.length === 0) && <span className="hexp__svc">—</span>}
                            </div>
                            <div className="hexp__col hexp__col--note">
                              <span className="hexp__lbl">Ghi chú</span>
                              {note ? (
                                <span className="hexp__note hexp__note--has">{note}</span>
                              ) : (
                                <span className="hexp__note hexp__note--empty">Không có ghi chú</span>
                              )}
                            </div>
                            <div className="hexp__col hexp__col--pay">
                              <span className="hexp__lbl">Thanh toán</span>
                              <span className={`hexp__pay ${payTone}`}>{PAY_LABEL[ps] || ps}</span>
                              <span className={`hexp__pay ${payTone}`}>{formatVND(od.total_amount)}</span>
                            </div>
                            <div className="hexp__col hexp__col--acts">
                              <button className="btn btn--ghost" onClick={() => window.print()}>In lại bill</button>
                              <button className="btn btn--ghost" onClick={() => navigate(`/orders/${o.id}`)}>Xem chi tiết</button>
                            </div>
                          </div>

                          {/* HÀNG 2: timeline 4 bước — chấm 16px + thanh nối liền (border-top ngăn). */}
                          <div className="hexp__tl">
                            <div className="hexp__tlhead">Nhật ký thời gian</div>
                            <div className="htl">
                              {buildTimeline(od).map((s, i) => (
                                <Fragment key={s.label}>
                                  {i > 0 && (
                                    <div className="htl__link">
                                      <span className={`htl__bar ${s.at ? (s.danger ? 'is-cancel' : 'is-done') : ''}`} />
                                    </div>
                                  )}
                                  <div className={`htl__step ${s.at ? 'is-done' : 'is-todo'} ${s.danger ? 'is-cancel' : ''}`}>
                                    <span className="htl__time">{s.at ? formatPickupBoard(s.at) : '—'}</span>
                                    <span className="htl__dotrow"><span className="htl__dot" /></span>
                                    <span className="htl__name">{s.label}</span>
                                  </div>
                                </Fragment>
                              ))}
                            </div>
                          </div>
                        </>
                      )
                    })()}
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
