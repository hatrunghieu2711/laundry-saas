import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Receipt from '../components/Receipt'
import { ApiError, api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'
import {
  CANCELLABLE,
  NEXT_STATUS,
  ORDER_STATUS,
  PAYMENT_STATUS,
  PREV_STATUS,
} from '../lib/orders'

// "Đơn hàng" (Stage 3.9): Kanban mặc định + chuyển Danh sách; search mã/tên khách;
// thao tác nhanh trên thẻ (→ tiến, ← lùi, ☰ menu).
const COLUMNS = [
  { key: 'created', label: 'Mới nhận' },
  { key: 'washing', label: 'Đang giặt' },
  { key: 'drying', label: 'Đang sấy' },
  { key: 'ready', label: 'Sẵn sàng' },
  { key: 'delivered', label: 'Đã giao' },
]
const BORDER = {
  unpaid: 'bl--unpaid',
  partial: 'bl--partial',
  paid: 'bl--paid',
  debt: 'bl--debt',
  refunded: 'bl--refunded',
}
// Bộ lọc danh sách (gồm cả trạng thái cuối để xem lại).
const LIST_STATUS = [
  { key: 'all', label: 'Tất cả', statuses: null },
  { key: 'active', label: 'Đang xử lý', statuses: ['created', 'washing', 'drying', 'ready'] },
  { key: 'ready', label: 'Sẵn sàng', statuses: ['ready'] },
  { key: 'delivered', label: 'Đã giao', statuses: ['delivered'] },
  { key: 'completed', label: 'Hoàn tất', statuses: ['completed'] },
  { key: 'cancelled', label: 'Đã hủy', statuses: ['cancelled'] },
]
const PAY_FILTERS = [
  { key: null, label: 'Mọi TT' },
  { key: 'unpaid', label: 'Chưa thu' },
  { key: 'paid', label: 'Đã thu' },
  { key: 'debt', label: 'Nợ' },
]
const REFRESH_MS = 30000
const LIMIT = 30

// Lùi được khi: trong nhóm xử lý (washing/drying/ready) hoặc delivered chưa thu.
function canRevert(o) {
  if (['washing', 'drying', 'ready'].includes(o.order_status)) return true
  if (o.order_status === 'delivered') return o.payment_status === 'unpaid'
  return false
}

export default function Board() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'

  const [view, setView] = useState('kanban') // kanban | list
  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(null)
  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')

  const [board, setBoard] = useState(null)
  const [list, setList] = useState([])
  const [total, setTotal] = useState(0)
  const [offset, setOffset] = useState(0)
  const [statusKey, setStatusKey] = useState('all')
  const [payKey, setPayKey] = useState(null)

  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [busy, setBusy] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)

  const [menuFor, setMenuFor] = useState(null) // id thẻ đang mở ☰
  const [payModal, setPayModal] = useState(null) // {id, code} cần thu khi giao
  const [cancelTarget, setCancelTarget] = useState(null) // {id, code}
  const [printData, setPrintData] = useState(null) // {order, paid}
  const menuRef = useRef(null)

  useEffect(() => {
    if (!isOwner) return
    api
      .get('/branches?limit=200')
      .then((p) => setBranches(p.items.filter((b) => b.status === 'active')))
      .catch(() => {})
  }, [isOwner])

  // debounce search → q
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(t)
  }, [search])

  const buildParams = useCallback(() => {
    const p = new URLSearchParams()
    if (isOwner && branchId) p.set('branch_id', branchId)
    if (q) p.set('q', q)
    return p
  }, [isOwner, branchId, q])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      if (view === 'kanban') {
        const d = await api.get(`/orders/board?${buildParams()}`)
        setBoard(d)
        setUpdatedAt(new Date())
      } else {
        const p = buildParams()
        p.set('limit', LIMIT)
        p.set('offset', 0)
        const sf = LIST_STATUS.find((s) => s.key === statusKey)
        if (sf?.statuses) sf.statuses.forEach((s) => p.append('order_status', s))
        if (payKey) p.append('payment_status', payKey)
        const d = await api.get(`/orders?${p}`)
        setList(d.items)
        setTotal(d.total)
        setOffset(d.items.length)
      }
    } catch (err) {
      setError(err?.message || 'Không tải được đơn hàng')
    } finally {
      setLoading(false)
    }
  }, [view, buildParams, statusKey, payKey])

  useEffect(() => {
    load()
  }, [load])

  // Tự refresh Kanban định kỳ.
  useEffect(() => {
    if (view !== 'kanban') return undefined
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [view, load])

  // Đóng menu thẻ khi bấm ra ngoài.
  useEffect(() => {
    if (menuFor == null) return undefined
    const onDown = (e) => {
      if (menuRef.current && !menuRef.current.contains(e.target)) setMenuFor(null)
    }
    document.addEventListener('pointerdown', onDown)
    return () => document.removeEventListener('pointerdown', onDown)
  }, [menuFor])

  // In phiếu sau khi nạp được order.
  useEffect(() => {
    if (!printData) return
    const t = setTimeout(() => {
      window.print()
      setPrintData(null)
    }, 120)
    return () => clearTimeout(t)
  }, [printData])

  const loadMore = async () => {
    const p = buildParams()
    p.set('limit', LIMIT)
    p.set('offset', offset)
    const sf = LIST_STATUS.find((s) => s.key === statusKey)
    if (sf?.statuses) sf.statuses.forEach((s) => p.append('order_status', s))
    if (payKey) p.append('payment_status', payKey)
    setLoading(true)
    try {
      const d = await api.get(`/orders?${p}`)
      setList((prev) => [...prev, ...d.items])
      setOffset((o) => o + d.items.length)
    } catch (err) {
      setError(err?.message || '')
    } finally {
      setLoading(false)
    }
  }

  // ── thao tác thẻ ──
  const forward = async (o) => {
    const next = NEXT_STATUS[o.order_status]
    if (!next) return
    setBusy(true)
    setError('')
    try {
      const r = await api.patch(`/orders/${o.id}/status`, { order_status: next })
      if (r?.requires_payment) setPayModal({ id: o.id, code: o.order_code })
      else await load()
    } catch (err) {
      setError(err?.message || 'Không đổi được trạng thái')
    } finally {
      setBusy(false)
    }
  }

  const backward = async (o) => {
    const prev = PREV_STATUS[o.order_status]
    if (!prev) return
    setBusy(true)
    setError('')
    try {
      await api.patch(`/orders/${o.id}/status`, { order_status: prev })
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'CANNOT_REVERT_PAID_DELIVERY') {
        setError('Không thể lùi đơn đã thu tiền.')
      } else {
        setError(err?.message || 'Không lùi được trạng thái')
      }
    } finally {
      setBusy(false)
    }
  }

  const recordDebt = async () => {
    if (!payModal) return
    setBusy(true)
    setError('')
    try {
      await api.post('/payments', {
        order_id: payModal.id,
        amount: 0,
        payment_method: 'cash',
        transaction_type: 'debt',
      })
      setPayModal(null)
      await load()
    } catch (err) {
      setError(
        err instanceof ApiError && err.code === 'NO_OPEN_SHIFT'
          ? 'Cần mở ca trước khi ghi nợ.'
          : err?.message || 'Không ghi nợ được',
      )
    } finally {
      setBusy(false)
    }
  }

  const doCancel = async () => {
    if (!cancelTarget) return
    setBusy(true)
    setError('')
    try {
      await api.del(`/orders/${cancelTarget.id}`)
      setCancelTarget(null)
      await load()
    } catch (err) {
      setError(err?.message || 'Không hủy được đơn')
    } finally {
      setBusy(false)
    }
  }

  const reprint = async (id) => {
    setMenuFor(null)
    setError('')
    try {
      const order = await api.get(`/orders/${id}`)
      const pays = await api.get(`/payments?order_id=${id}&limit=200`)
      const paid = pays.items.reduce((s, p) => s + toNumber(p.amount), 0)
      setPrintData({ order, paid })
    } catch (err) {
      setError(err?.message || 'Không in được phiếu')
    }
  }

  const branchPicker = isOwner && branches.length > 0 && (
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
  )

  const s = board?.summary
  const cols = board?.columns || {}

  return (
    <div className="board">
      {branchPicker}

      <div className="orders-top">
        <input
          className="input orders-top__search"
          type="search"
          placeholder="🔍 Tìm mã đơn hoặc tên khách…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        <div className="view-toggle">
          <button
            className={`view-toggle__btn ${view === 'kanban' ? 'view-toggle__btn--active' : ''}`}
            onClick={() => setView('kanban')}
          >
            ▦ Bảng
          </button>
          <button
            className={`view-toggle__btn ${view === 'list' ? 'view-toggle__btn--active' : ''}`}
            onClick={() => setView('list')}
          >
            ☰ Danh sách
          </button>
        </div>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {view === 'kanban' ? (
        <>
          {s && (
            <div className="board__bar">
              <div className="board__stat"><span className="board__stat-num">{s.total_orders}</span><span className="board__stat-lbl">Ở tiệm</span></div>
              <div className="board__stat board__stat--unpaid"><span className="board__stat-num">{s.unpaid}</span><span className="board__stat-lbl">Chưa thu</span></div>
              <div className="board__stat board__stat--paid"><span className="board__stat-num">{s.paid}</span><span className="board__stat-lbl">Đã thu</span></div>
              <div className="board__stat board__stat--debt"><span className="board__stat-num">{s.debt}</span><span className="board__stat-lbl">Nợ</span></div>
              <div className="board__stat board__stat--overdue"><span className="board__stat-num">{s.overdue}</span><span className="board__stat-lbl">Trễ hẹn</span></div>
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

          {board && (
            <div className="board__cols">
              {COLUMNS.map((col) => {
                const items = cols[col.key] || []
                return (
                  <section className="board__col" key={col.key}>
                    <div className="board__col-head">
                      <span>{col.label}</span>
                      <span className="board__col-count">{items.length}</span>
                    </div>
                    <div className="board__col-body">
                      {items.length === 0 ? (
                        <p className="board__empty">—</p>
                      ) : (
                        items.map((o) => {
                          const ps = PAYMENT_STATUS[o.payment_status] || { label: o.payment_status, cls: '' }
                          const next = NEXT_STATUS[o.order_status]
                          return (
                            <div key={o.id} className={`board__card ${BORDER[o.payment_status] || ''}`}>
                              <button className="board__card-main" onClick={() => navigate(`/orders/${o.id}`)}>
                                <div className="board__card-top">
                                  <span className="board__card-code">{o.order_code}</span>
                                  {o.is_overdue && <span className="board__overdue">TRỄ</span>}
                                </div>
                                <div className="board__card-cust">{o.customer_name || 'Khách lẻ'}</div>
                                <div className="board__card-bot">
                                  <span className="board__card-total">{formatVND(o.total_amount)}</span>
                                  <span className={`board__card-pickup ${o.is_overdue ? 'is-overdue' : ''}`}>🕒 {formatPickupShort(o.pickup_at)}</span>
                                </div>
                                <span className={`badge-ps badge-ps--xs ${ps.cls}`}>{ps.label}</span>
                              </button>
                              <div className="board__card-actions">
                                {canRevert(o) && (
                                  <button className="card-act" title="Lùi trạng thái" disabled={busy} onClick={() => backward(o)}>←</button>
                                )}
                                {next && (
                                  <button className="card-act card-act--fwd" title={`Sang: ${ORDER_STATUS[next]}`} disabled={busy} onClick={() => forward(o)}>
                                    {ORDER_STATUS[next]} →
                                  </button>
                                )}
                                <div className="card-act__menu" ref={menuFor === o.id ? menuRef : null}>
                                  <button className="card-act" title="Khác" onClick={() => setMenuFor(menuFor === o.id ? null : o.id)}>☰</button>
                                  {menuFor === o.id && (
                                    <div className="card-menu">
                                      <button className="card-menu__item" onClick={() => navigate(`/orders/${o.id}`)}>Xem chi tiết</button>
                                      {o.payment_status !== 'paid' && (
                                        <button className="card-menu__item" onClick={() => navigate(`/orders/${o.id}/pay`)}>💵 Thu tiền</button>
                                      )}
                                      <button className="card-menu__item" onClick={() => reprint(o.id)}>🖨️ In lại phiếu</button>
                                      {CANCELLABLE.has(o.order_status) && (
                                        <button className="card-menu__item card-menu__item--danger" onClick={() => { setMenuFor(null); setCancelTarget({ id: o.id, code: o.order_code }) }}>Hủy đơn</button>
                                      )}
                                    </div>
                                  )}
                                </div>
                              </div>
                            </div>
                          )
                        })
                      )}
                    </div>
                  </section>
                )
              })}
            </div>
          )}
        </>
      ) : (
        <>
          <div className="chip-row">
            {LIST_STATUS.map((f) => (
              <button key={f.key} className={`chip chip--sm ${statusKey === f.key ? 'chip--active' : ''}`} onClick={() => setStatusKey(f.key)}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="chip-row">
            {PAY_FILTERS.map((f) => (
              <button key={f.key || 'all'} className={`chip chip--sm ${payKey === f.key ? 'chip--active' : ''}`} onClick={() => setPayKey(f.key)}>
                {f.label}
              </button>
            ))}
          </div>

          {list.length === 0 && !loading && <p className="shift__hint">Không có đơn nào.</p>}
          <div className="order-list">
            {list.map((o) => {
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
          {list.length < total && (
            <button className="btn btn--ghost btn--block" onClick={loadMore} disabled={loading}>
              {loading ? 'Đang tải…' : `Tải thêm (${list.length}/${total})`}
            </button>
          )}
        </>
      )}

      {/* Popup giao đơn còn nợ → bắt buộc xử lý */}
      {payModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal">
            <h3 className="modal__title">⚠️ Đơn {payModal.code} chưa thanh toán</h3>
            <p className="modal__text">Đã giao nhưng <strong>chưa thu đủ tiền</strong>. Chọn cách xử lý:</p>
            {error && <div className="alert alert--error">{error}</div>}
            <div className="modal__actions">
              <button className="btn btn--primary btn--xl btn--block" onClick={() => navigate(`/orders/${payModal.id}/pay`)}>💵 Thu tiền</button>
              <button className="btn btn--ghost btn--lg btn--block" onClick={recordDebt} disabled={busy}>📝 Ghi nợ (khách trả sau)</button>
            </div>
          </div>
        </div>
      )}

      {/* Xác nhận hủy đơn */}
      {cancelTarget && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal">
            <h3 className="modal__title">Hủy đơn {cancelTarget.code}?</h3>
            <p className="modal__text">Đơn sẽ chuyển sang trạng thái “Đã hủy”. Không hoàn tác được.</p>
            {error && <div className="alert alert--error">{error}</div>}
            <div className="modal__actions modal__actions--row">
              <button className="btn btn--ghost btn--lg" onClick={() => setCancelTarget(null)} disabled={busy}>Không</button>
              <button className="btn btn--danger btn--xl" onClick={doCancel} disabled={busy}>Chắc chắn hủy</button>
            </div>
          </div>
        </div>
      )}

      {printData && <Receipt order={printData.order} paid={printData.paid} />}
    </div>
  )
}
