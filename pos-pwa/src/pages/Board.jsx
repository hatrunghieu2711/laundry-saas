import { useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import Receipt from '../components/Receipt'
import Lien2PrintButton from '../components/Lien2PrintButton'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { useTopbarSlot } from '../context/TopbarSlotContext'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'
import { NEXT_STATUS, ORDER_STATUS, PREV_STATUS } from '../lib/orders'

// Dashboard "Đơn hàng" (Stage 6.10 layout + 6.12 thẻ thao tác): 3 cột tại tiệm.
//   - GỘP washing + drying → "Đang xử lý"; BỎ "Đã giao" (đã giao rời board).
//   - Thẻ: nội dung gọn + nút ← → đổi trạng thái + ☰ menu + popup giao‑thu.
const COLUMNS = [
  { key: 'created', label: 'Mới nhận', statuses: ['created'] },
  { key: 'processing', label: 'Đang xử lý', statuses: ['washing', 'drying'] },
  { key: 'ready', label: 'Sẵn sàng', statuses: ['ready'] },
]
// Badge thanh toán (mẫu chuẩn 6.14).
const BADGE = {
  paid: { label: 'Đã thu', cls: 'bps--paid' },
  unpaid: { label: 'Chưa thu', cls: 'bps--unpaid' },
  partial: { label: 'Thu 1 phần', cls: 'bps--partial' },
  debt: { label: 'Ghi nợ', cls: 'bps--debt' },
  refunded: { label: 'Đã hoàn', cls: 'bps--refunded' },
}
// Viền trái: xanh khi ĐÃ THU đủ; đỏ khi còn nợ tiền (unpaid/partial/debt); xám = hoàn.
const cardMod = (ps) =>
  ps === 'paid' ? 'board3__card--paid' : ps === 'refunded' ? 'board3__card--ref' : 'board3__card--owe'
const REFRESH_MS = 30000

// Icon SVG inline (kiểu Tabler) — KHÔNG phụ thuộc CDN/webfont, hợp PWA offline Sunmi.
const ICON_PATHS = {
  'arrow-left': 'M5 12h14 M5 12l6 6 M5 12l6 -6',
  'arrow-right': 'M5 12h14 M13 6l6 6 M13 18l6 -6',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  note: 'M5 4h8l5 5v11H5z M13 4v5h5',
}
function Icon({ name, className = 'ic' }) {
  return (
    <svg
      className={className}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={ICON_PATHS[name]} />
    </svg>
  )
}

// Di chuyển 1 thẻ giữa các mảng cột (cập nhật lạc quan).
function moveCard(board, orderId, from, to) {
  const cols = { ...board.columns }
  const card = (cols[from] || []).find((o) => o.id === orderId)
  cols[from] = (cols[from] || []).filter((o) => o.id !== orderId)
  if (card) cols[to] = [...(cols[to] || []), { ...card, order_status: to }]
  return { ...board, columns: cols }
}

export default function Board() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'
  const { branchId } = useBranch()
  const { slotEl } = useTopbarSlot()

  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [board, setBoard] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)
  const [autoPrint, setAutoPrint] = useState(false)

  const [busyId, setBusyId] = useState(null) // thẻ đang đổi trạng thái
  const [toast, setToast] = useState('')
  const [sheet, setSheet] = useState(null) // {order, full} — bottom sheet ☰
  const [payModal, setPayModal] = useState(null) // {order, remaining}
  const [payMethod, setPayMethod] = useState('cash')
  const [debtMode, setDebtMode] = useState(false)
  const [debtReason, setDebtReason] = useState('')
  const [payBusy, setPayBusy] = useState(false)
  const [printData, setPrintData] = useState(null) // {order, paid}
  const [noteModal, setNoteModal] = useState(null) // {code, notes} — popup ghi chú
  const toastTimer = useRef(null)

  const showToast = useCallback((msg) => {
    setToast(msg)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(''), 3000)
  }, [])

  // debounce search → q
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(t)
  }, [search])

  // Cờ tự-in bill từ tenant settings (cho luồng giao‑thu).
  useEffect(() => {
    api.get('/settings/pos').then((s) => setAutoPrint(s.auto_print_receipt !== false)).catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const p = new URLSearchParams()
      if (isOwner && branchId) p.set('branch_id', branchId)
      if (q) p.set('q', q)
      const d = await api.get(`/orders/board?${p}`)
      setBoard(d)
      setUpdatedAt(new Date())
    } catch (err) {
      setError(err?.message || 'Không tải được đơn hàng')
    } finally {
      setLoading(false)
    }
  }, [isOwner, branchId, q])

  useEffect(() => { load() }, [load])

  // Tự refresh định kỳ — TẠM DỪNG khi đang mở popup giao‑thu (tránh thẻ nhảy).
  useEffect(() => {
    if (payModal) return undefined
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load, payModal])

  // In bill: render Receipt rồi window.print() (cơ chế như OrderDetail).
  useEffect(() => {
    if (!printData) return undefined
    const t = setTimeout(() => {
      window.print()
      setPrintData(null)
    }, 150)
    return () => clearTimeout(t)
  }, [printData])

  const printBill = useCallback(async (id) => {
    try {
      const order = await api.get(`/orders/${id}`)
      const pays = await api.get(`/payments?order_id=${id}&limit=200`)
      const paid = pays.items.reduce((s, p) => s + toNumber(p.amount), 0)
      setPrintData({ order, paid })
    } catch {
      showToast('Không in được bill')
    }
  }, [showToast])

  // ── Đổi trạng thái (← →) ──────────────────────────────────────────────
  const move = async (o, dir) => {
    const target = dir === 'fwd' ? NEXT_STATUS[o.order_status] : PREV_STATUS[o.order_status]
    if (!target || busyId) return
    if (target === 'delivered') return deliver(o)

    const from = o.order_status
    setBusyId(o.id)
    setBoard((prev) => moveCard(prev, o.id, from, target)) // optimistic
    try {
      await api.patch(`/orders/${o.id}/status`, { order_status: target })
    } catch (err) {
      setBoard((prev) => moveCard(prev, o.id, target, from)) // revert
      showToast(err?.message || 'Không đổi được trạng thái')
    } finally {
      setBusyId(null)
    }
  }

  // → tới 'delivered' (PAY-FIRST, Stage 6.13): XỬ LÝ TIỀN TRƯỚC, GIAO SAU.
  // Đơn KHÔNG bao giờ sang delivered khi chưa xử lý tiền → bỏ luồng "lùi" mong manh.
  const deliver = async (o) => {
    const needsPay = o.payment_status === 'unpaid' || o.payment_status === 'partial'
    if (!needsPay) {
      // Đã xử lý tiền (paid/debt/refunded) → PATCH delivered thẳng.
      setBusyId(o.id)
      try {
        await api.patch(`/orders/${o.id}/status`, { order_status: 'delivered' })
        setBoard((prev) => moveCard(prev, o.id, o.order_status, 'delivered')) // rời board
      } catch (err) {
        showToast(err?.message || 'Không giao được đơn')
      } finally {
        setBusyId(null)
      }
      return
    }
    // Chưa thu → MỞ POPUP NGAY, CHƯA PATCH gì (đơn vẫn ở 'ready' trên server).
    setBusyId(o.id)
    try {
      const pays = await api.get(`/payments?order_id=${o.id}&limit=200`)
      const paid = pays.items.reduce((s, p) => s + toNumber(p.amount), 0)
      setPayMethod('cash'); setDebtMode(false); setDebtReason('')
      setPayModal({ order: o, remaining: toNumber(o.total_amount) - paid })
    } catch (err) {
      showToast(err?.message || 'Không mở được màn thu tiền, thử lại.')
    } finally {
      setBusyId(null)
    }
  }

  const payErr = (err) => {
    if (err instanceof ApiError && err.code === 'NO_OPEN_SHIFT') return 'Cần mở ca trước khi thu / ghi nợ.'
    if (err instanceof ApiError && err.code === 'DEBT_REASON_REQUIRED') return 'Nhập lý do nợ.'
    return err?.message || 'Không xử lý được'
  }

  // Tiền đã xử lý xong → GIỜ MỚI chuyển 'delivered'. KHÔNG nuốt lỗi: nếu PATCH cuối
  // lỗi thì tiền đã vào sổ đúng, đơn vẫn ở 'ready' (paid/debt) — báo rõ để bấm lại giao.
  const finishDeliver = async (orderId, kind) => {
    try {
      await api.patch(`/orders/${orderId}/status`, { order_status: 'delivered' })
    } catch {
      setPayModal(null)
      showToast(
        kind === 'debt'
          ? 'Đã ghi nợ, nhưng chưa cập nhật trạng thái — bấm lại để giao.'
          : 'Đã thu tiền, nhưng chưa cập nhật trạng thái — bấm lại để giao.',
      )
      await load()
      return
    }
    setPayModal(null)
    if (autoPrint) await printBill(orderId)
    await load()
  }

  const payFull = async () => {
    setPayBusy(true)
    try {
      await api.post('/payments', {
        order_id: payModal.order.id,
        amount: payModal.remaining,
        payment_method: payMethod,
        transaction_type: 'payment',
      })
      await finishDeliver(payModal.order.id, 'pay')
    } catch (err) {
      showToast(payErr(err))
    } finally {
      setPayBusy(false)
    }
  }

  const payDebt = async () => {
    const reason = debtReason.trim()
    if (!reason) { showToast('Nhập lý do nợ.'); return }
    setPayBusy(true)
    try {
      await api.post('/payments', {
        order_id: payModal.order.id,
        amount: 0,
        payment_method: 'cash',
        transaction_type: 'debt',
        reason,
      })
      await finishDeliver(payModal.order.id, 'debt')
    } catch (err) {
      showToast(payErr(err))
    } finally {
      setPayBusy(false)
    }
  }

  // PAY-FIRST: khi popup mở, đơn CHƯA hề sang 'delivered' → đóng popup KHÔNG gọi
  // server lần nào (không PATCH, không lùi, không load). Đơn nguyên ở 'ready'.
  // Đây là điểm cốt lõi xoá khe W1/W2/W3 (không còn trạng thái delivered‑chưa‑thu).
  const dismissPay = () => setPayModal(null)

  // ── Bottom sheet ☰ ────────────────────────────────────────────────────
  const openSheet = async (o) => {
    setSheet({ order: o, full: null })
    try {
      const full = await api.get(`/orders/${o.id}`)
      setSheet((s) => (s && s.order.id === o.id ? { ...s, full } : s))
    } catch {
      /* để full=null → nút In liên 2 hiện "Đang tải…" */
    }
  }

  const cols = board?.columns || {}
  const columnItems = COLUMNS.map((col) => {
    const items = col.statuses.flatMap((s) => cols[s] || [])
    items.sort((a, b) => (a.pickup_at < b.pickup_at ? -1 : a.pickup_at > b.pickup_at ? 1 : 0))
    return { ...col, items }
  })
  const shown = columnItems.flatMap((c) => c.items)
  const stat = {
    total: shown.length,
    unpaid: shown.filter((o) => o.payment_status === 'unpaid' || o.payment_status === 'partial').length,
    paid: shown.filter((o) => o.payment_status === 'paid').length,
    debt: shown.filter((o) => o.payment_status === 'debt').length,
  }

  const topControls = (
    <div className="topbar-actions">
      <input
        className="topbar-actions__search"
        type="search"
        placeholder="🔍 Tìm mã đơn / tên / SĐT…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="Tìm đơn"
      />
      <button className="topbar-actions__refresh" onClick={load} disabled={loading}>
        {loading ? '…' : '↻ Làm mới'}
      </button>
    </div>
  )

  return (
    <div className="board">
      {slotEl && createPortal(topControls, slotEl)}

      <div className="board-stats">
        <span>Ở tiệm <b>{stat.total}</b></span>
        <span className="board-stats__dot">·</span>
        <span>Chưa thu <b className="board-stats__warn">{stat.unpaid}</b></span>
        <span className="board-stats__dot">·</span>
        <span>Đã thu <b className="board-stats__success">{stat.paid}</b></span>
        <span className="board-stats__dot">·</span>
        <span>Nợ <b>{stat.debt}</b></span>
        <div className="board-stats__spacer" />
        {updatedAt && (
          <span className="board-stats__updated">
            Cập nhật {String(updatedAt.getHours()).padStart(2, '0')}:
            {String(updatedAt.getMinutes()).padStart(2, '0')}
          </span>
        )}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      <div className="board3">
        {columnItems.map((col) => (
          <section className="board3__col" key={col.key}>
            <div className="board3__col-head">
              <span className="board3__col-title">{col.label}</span>
              <span className="board3__col-count">{col.items.length}</span>
            </div>
            <div className="board3__cards">
              {col.items.map((o) => {
                const badge = BADGE[o.payment_status] || { label: o.payment_status, cls: '' }
                const goDetail = () => navigate(`/orders/${o.id}`)
                return (
                  <div key={o.id} className={`board3__card ${cardMod(o.payment_status)}`}>
                    <div
                      className="board3__main"
                      role="button"
                      tabIndex={0}
                      onClick={goDetail}
                      onKeyDown={(e) => { if (e.key === 'Enter') goDetail() }}
                    >
                      <div className="board3__l1">
                        <span className="board3__codegrp">
                          <span className="board3__code">{o.order_code}</span>
                          {o.notes ? (
                            <button
                              className="board3__flag"
                              aria-label="Xem ghi chú"
                              onClick={(e) => { e.stopPropagation(); setNoteModal({ code: o.order_code, notes: o.notes }) }}
                            >
                              <Icon name="note" className="board3__flag-ic" />
                            </button>
                          ) : null}
                        </span>
                        <span className="board3__cust">{o.customer_name || 'Khách lẻ'}</span>
                      </div>
                      <div className="board3__l2">
                        <span className="board3__total">{formatVND(o.total_amount)}</span>
                        <span className={`bps ${badge.cls}`}>{badge.label}</span>
                      </div>
                      <div className="board3__l3">
                        <span className={`board3__time ${o.is_overdue ? 'is-late' : ''}`}>
                          {formatPickupShort(o.pickup_at)}
                        </span>
                        {o.is_overdue && <span className="board3__latetag">TRỄ</span>}
                      </div>
                    </div>
                    <div className="board3__actions">
                      <button
                        className="board3__act"
                        disabled={!PREV_STATUS[o.order_status] || busyId === o.id}
                        onClick={() => move(o, 'back')}
                        aria-label="Lùi trạng thái"
                      ><Icon name="arrow-left" /></button>
                      <button
                        className="board3__act board3__act--next"
                        disabled={busyId === o.id}
                        onClick={() => move(o, 'fwd')}
                        aria-label={`Sang ${ORDER_STATUS[NEXT_STATUS[o.order_status]] || ''}`}
                      ><Icon name="arrow-right" /></button>
                      <button
                        className="board3__act board3__act--menu"
                        onClick={() => openSheet(o)}
                        aria-label="Thao tác khác"
                      ><Icon name="menu" /></button>
                    </div>
                  </div>
                )
              })}
            </div>
          </section>
        ))}
      </div>

      {toast && <div className="toast" role="status">{toast}</div>}

      {/* ── Popup ghi chú (bấm icon note trên thẻ) ── */}
      {noteModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setNoteModal(null)}>
          <div className="modal note-modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="modal__title">Ghi chú · {noteModal.code}</h3>
            <p className="note-modal__text">{noteModal.notes}</p>
            <button className="btn btn--ghost btn--block" onClick={() => setNoteModal(null)}>Đóng</button>
          </div>
        </div>
      )}

      {/* ── Bottom sheet ☰: 3 thao tác ── */}
      {sheet && (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setSheet(null)}>
          <div className="sheet" onClick={(e) => e.stopPropagation()}>
            <div className="sheet__title">Đơn {sheet.order.order_code}</div>
            <button className="sheet__item" onClick={() => navigate(`/orders/${sheet.order.id}`)}>
              Xem chi tiết
            </button>
            <button
              className="sheet__item"
              onClick={() => { const id = sheet.order.id; setSheet(null); printBill(id) }}
            >
              🖨️ In lại bill
            </button>
            {sheet.full
              ? <Lien2PrintButton order={sheet.full} className="sheet__item" />
              : <button className="sheet__item" disabled>Đang tải liên 2…</button>}
            <button className="sheet__item sheet__cancel" onClick={() => setSheet(null)}>Đóng</button>
          </div>
        </div>
      )}

      {/* ── Popup GIAO‑THANH‑TOÁN (không nút "Bỏ qua"; đóng = không giao) ── */}
      {payModal && (
        <div className="modal-overlay" role="dialog" aria-modal="true" onClick={dismissPay}>
          <div className="modal" onClick={(e) => e.stopPropagation()}>
            <h3 className="modal__title">Giao đơn {payModal.order.order_code}</h3>
            <div className="pay-due">
              <span>Còn phải thu</span>
              <strong>{formatVND(payModal.remaining)}</strong>
            </div>

            <div className="pay-methods">
              {[['cash', '💵 Tiền mặt'], ['transfer', '🏦 Chuyển khoản']].map(([k, lbl]) => (
                <button
                  key={k}
                  className={`pay-method ${payMethod === k ? 'pay-method--on' : ''}`}
                  onClick={() => setPayMethod(k)}
                  disabled={payBusy}
                >{lbl}</button>
              ))}
            </div>

            {debtMode && (
              <label className="field">
                <span>Lý do nợ (bắt buộc)</span>
                <input
                  className="input"
                  value={debtReason}
                  onChange={(e) => setDebtReason(e.target.value)}
                  placeholder="VD: khách quen trả cuối tháng"
                  autoFocus
                />
              </label>
            )}

            <div className="modal__actions">
              <button className="btn btn--primary btn--xl btn--block" onClick={payFull} disabled={payBusy}>
                {payBusy && !debtMode ? 'Đang thu…' : `Thu đủ ${formatVND(payModal.remaining)}`}
              </button>
              {debtMode ? (
                <button className="btn btn--warn btn--lg btn--block" onClick={payDebt} disabled={payBusy || !debtReason.trim()}>
                  {payBusy ? 'Đang ghi nợ…' : 'Xác nhận ghi nợ'}
                </button>
              ) : (
                <button className="btn btn--ghost btn--lg btn--block" onClick={() => setDebtMode(true)} disabled={payBusy}>
                  📝 Ghi nợ (khách trả sau)
                </button>
              )}
            </div>
            <button className="pay-dismiss" onClick={dismissPay} disabled={payBusy}>
              Đóng — chưa giao đơn
            </button>
          </div>
        </div>
      )}

      {printData && <Receipt order={printData.order} paid={printData.paid} />}
    </div>
  )
}
