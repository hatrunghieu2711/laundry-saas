import { Fragment, useCallback, useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import Receipt from '../components/Receipt'
import Lien2PrintButton from '../components/Lien2PrintButton'
import { printViaIframe, setPrintMode } from '../lib/printQueue'
import CancelOrderModal from '../components/CancelOrderModal'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { useTopbarSlot } from '../context/TopbarSlotContext'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'
import { formatPickupBoard } from '../lib/datetime'
import { CANCELLABLE, ORDER_STATUS } from '../lib/orders'
import { buildTimeline } from '../lib/timeline'

// Dashboard "Đơn hàng" (Stage 6.10 layout + 6.12 thẻ thao tác): 3 cột tại tiệm.
//   - GỘP washing + drying → "Đang xử lý"; BỎ "Đã giao" (đã giao rời board).
//   - Thẻ: nội dung gọn + nút ← → đổi trạng thái + ☰ menu + popup giao‑thu.
const COLUMNS = [
  { key: 'created', label: 'Mới nhận', statuses: ['created'] },
  { key: 'processing', label: 'Đang xử lý', statuses: ['washing', 'drying'] },
  { key: 'ready', label: 'Sẵn sàng', statuses: ['ready'] },
]
const REFRESH_MS = 30000

// Màu giờ giao theo độ GẤP (tính ở FRONTEND từ pickup_at vs giờ hiện tại — so sánh
// 2 mốc thời gian TUYỆT ĐỐI nên KHÔNG lệch UTC; tự cập nhật theo chu kỳ refresh ~30s).
function timeUrgency(pickupAt) {
  if (!pickupAt) return ''
  const diffMin = (new Date(pickupAt).getTime() - Date.now()) / 60000
  if (diffMin < 0) return 'is-late' // đã quá giờ hẹn → đỏ
  if (diffMin <= 30) return 'is-soon' // còn ≤30 phút → cam
  return '' // còn xa → màu thường (vẫn đậm)
}

// Icon SVG inline (kiểu Tabler) — KHÔNG phụ thuộc CDN/webfont, hợp PWA offline Sunmi.
const ICON_PATHS = {
  'arrow-left': 'M5 12h14 M5 12l6 6 M5 12l6 -6',
  'arrow-right': 'M5 12h14 M13 6l6 6 M13 18l6 -6',
  menu: 'M4 6h16 M4 12h16 M4 18h16',
  note: 'M5 4h8l5 5v11H5z M13 4v5h5',
  truck: 'M2 5h12v10H2z M14 8h4l3 4v3h-7 M4 15a2 2 0 1 0 4 0a2 2 0 1 0 -4 0 M15 15a2 2 0 1 0 4 0a2 2 0 1 0 -4 0',
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

  const [busyId, setBusyId] = useState(null) // thẻ đang đổi trạng thái
  const [toast, setToast] = useState(null) // {msg, action?:{label,fn}}
  const [sheet, setSheet] = useState(null) // {order, full} — bottom sheet ☰
  const [payModal, setPayModal] = useState(null) // {order, remaining}
  const [payMethod, setPayMethod] = useState('cash')
  const [debtMode, setDebtMode] = useState(false)
  const [debtReason, setDebtReason] = useState('')
  const [payBusy, setPayBusy] = useState(false)
  const [printData, setPrintData] = useState(null) // {order, paid}
  const [noteModal, setNoteModal] = useState(null) // {code, notes} — popup ghi chú
  const [cancelModal, setCancelModal] = useState(null) // order cần hủy (Stage 6.28)
  const toastTimer = useRef(null)

  const showToast = useCallback((msg, action = null, ms = 3000) => {
    setToast({ msg, action })
    if (toastTimer.current) clearTimeout(toastTimer.current)
    toastTimer.current = setTimeout(() => setToast(null), ms)
  }, [])

  // debounce search → q
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(t)
  }, [search])

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

  // In bill: render Receipt rồi window.print() (cơ chế như OrderDetail). setPrintMode('bill')
  // → Receipt mount tường minh (tránh kẹt 'lien2' từ lần in nhãn trước).
  useEffect(() => {
    if (!printData) return undefined
    setPrintMode('bill')
    const t = setTimeout(() => {
      printViaIframe('.print-receipt') // clone .print-receipt → in iframe (print context sạch /T2)
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

  // ── Đổi trạng thái theo CỘT (← →): mỗi lần bấm sang HẲN cột kế/trước ──────
  // (Stage 6.17) Nhóm cột định nghĩa 1 nơi DUY NHẤT = COLUMNS. Nút → nhảy tới
  // trạng thái ĐẦU của cột kế trong 1 request → đơn washing/drying ở "Đang xử lý"
  // bấm → 1 lần là sang "Sẵn sàng" (không còn kẹt trong cột gộp).
  const move = async (o, dir) => {
    if (busyId) return
    const ci = COLUMNS.findIndex((c) => c.statuses.includes(o.order_status))
    if (ci < 0) return
    if (dir === 'fwd') {
      const nextCol = COLUMNS[ci + 1]
      if (!nextCol) return deliver(o) // hết cột tại tiệm (Sẵn sàng) → giao (pay-first)
      return patchStatus(o, nextCol.statuses[0]) // nhảy tới ĐẦU cột kế
    }
    const prevCol = COLUMNS[ci - 1]
    if (!prevCol) return // Mới nhận → không có cột trước
    // Lùi về bước GẦN NHẤT của cột trước (trạng thái cuối của cột đó).
    return patchStatus(o, prevCol.statuses[prevCol.statuses.length - 1])
  }

  const patchStatus = async (o, target) => {
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
      // Đã xử lý tiền (paid/debt/refunded) → GIAO THẲNG (không popup) + toast Hoàn tác.
      setBusyId(o.id)
      try {
        await api.patch(`/orders/${o.id}/status`, { order_status: 'delivered' })
        setBoard((prev) => moveCard(prev, o.id, o.order_status, 'delivered')) // rời board
        showToast(`Đã giao đơn ${o.order_code}`, { label: 'Hoàn tác', fn: () => undoDeliver(o) }, 5000)
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

  // Hoàn tác GIAO (Stage 6.18): lùi delivered→ready. Backend cho phép mọi payment_status
  // (chỉ đổi trạng thái, KHÔNG đụng tiền). Đơn quay lại cột "Sẵn sàng".
  const undoDeliver = async (o) => {
    setToast(null)
    if (toastTimer.current) clearTimeout(toastTimer.current)
    try {
      await api.patch(`/orders/${o.id}/status`, { order_status: 'ready' })
      await load()
    } catch (err) {
      showToast(err?.message || 'Không hoàn tác được')
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
    await load() // (Stage 6.18) BỎ tự in bill khi giao — in bill chỉ qua menu ☰.
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
        placeholder="Tìm mã đơn / tên / SĐT…"
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
        {columnItems.map((col, colIdx) => (
          <section className="board3__col" key={col.key}>
            <div className="board3__col-head">
              <span className="board3__col-title">{col.label}</span>
              <span className="board3__col-count">{col.items.length}</span>
            </div>
            <div className="board3__cards">
              {col.items.map((o) => {
                // Bấm THÂN thẻ → mở popup ☰ (6.54), KHÔNG sang /orders/:id. ← → ☰ nằm ở
                // board3__actions (ANH EM với board3__main) nên không lan; nút note bên trong
                // đã stopPropagation. Vào chi tiết qua nút "Chi tiết" trong popup.
                const openCard = () => openSheet(o)
                const paidFull = o.payment_status === 'paid'
                // Nhãn cam/đỏ CHỈ cho đơn CHƯA xong (created/washing/drying); đơn 'ready'
                // (đã giặt xong) → giờ dạng text thường, không nhãn (mốc hết nghĩa "gấp").
                const timeCls = o.order_status === 'ready' ? '' : timeUrgency(o.pickup_at)
                return (
                  <div key={o.id} className={`board3__card ${paidFull ? 'board3__card--paid' : 'board3__card--owe'}`}>
                    <div
                      className="board3__main"
                      role="button"
                      tabIndex={0}
                      onClick={openCard}
                      onKeyDown={(e) => { if (e.key === 'Enter') openCard() }}
                    >
                      <div className="board3__l1">
                        <span className="board3__code">{o.order_code}</span>
                        <span className={`board3__money ${paidFull ? 'board3__money--paid' : 'board3__money--unpaid'}`}>
                          {formatVND(o.total_amount)}
                        </span>
                      </div>
                      <div className="board3__l2">
                        <span className="board3__l2left">
                          {/* TODO: cờ đơn giao — làm sau khi có module giao/COD (chưa có field is_delivery) */}
                          {o.is_delivery ? <Icon name="truck" className="board3__flag-ic board3__flag--ship" /> : null}
                          {o.notes ? (
                            <button
                              className="board3__flag board3__flag--note"
                              aria-label="Xem ghi chú"
                              onClick={(e) => { e.stopPropagation(); setNoteModal({ code: o.order_code, notes: o.notes }) }}
                            >
                              <Icon name="note" className="board3__flag-ic" />
                            </button>
                          ) : null}
                          <span className="board3__cust">{o.customer_name || 'Khách lẻ'}</span>
                        </span>
                        <span className={`board3__time ${timeCls}`}>
                          {formatPickupBoard(o.pickup_at)}
                        </span>
                      </div>
                    </div>
                    <div className="board3__actions">
                      <button
                        className="board3__act"
                        disabled={colIdx === 0 || busyId === o.id}
                        onClick={() => move(o, 'back')}
                        aria-label={colIdx > 0 ? `Lùi về ${COLUMNS[colIdx - 1].label}` : 'Lùi'}
                      ><Icon name="arrow-left" /></button>
                      <button
                        className="board3__act board3__act--next"
                        disabled={busyId === o.id}
                        onClick={() => move(o, 'fwd')}
                        aria-label={COLUMNS[colIdx + 1] ? `Sang ${COLUMNS[colIdx + 1].label}` : 'Giao đơn'}
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

      {toast && (
        <div className="toast" role="status">
          <span>{toast.msg}</span>
          {toast.action && (
            <button className="toast__action" onClick={toast.action.fn}>{toast.action.label}</button>
          )}
        </div>
      )}

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

      {/* ── Bottom sheet ☰: thẻ đầy đủ (6.45) ── */}
      {sheet && (() => {
        const o = sheet.order
        const full = sheet.full
        const paid = o.payment_status === 'paid'
        const colIdx = COLUMNS.findIndex((c) => c.statuses.includes(o.order_status))
        const note = (full?.notes ?? o.notes ?? '').trim()
        const phone = full?.customer_phone || o.customer_phone
        return (
          <div className="modal-overlay" role="dialog" aria-modal="true" onClick={() => setSheet(null)}>
            <div className="sheet sheet--full" onClick={(e) => e.stopPropagation()}>
              <div className="sheet__grip" />

              {/* HEADER: mã + badge thu + badge trạng thái */}
              <div className="sheet__hd">
                <span className="sheet__code">{o.order_code}</span>
                <span className={`sheet__pay ${paid ? 'is-ok' : 'is-due'}`}>{paid ? 'Đã thu' : 'Chưa thu'}</span>
                <span className="sheet__status">{ORDER_STATUS[o.order_status] || o.order_status}</span>
              </div>

              {/* KHÁCH + TIỀN */}
              <div className="sheet__cust">
                <span className="sheet__cust-l">Khách: {o.customer_name || 'Khách lẻ'}{phone ? ` · ${phone}` : ''}</span>
                <span className="sheet__cust-r">
                  <span className="sheet__total">{formatVND(o.total_amount)}</span>
                  <span className={`sheet__paytag ${paid ? 'is-ok' : 'is-due'}`}>{paid ? 'Đã thu' : 'Chưa thu'}</span>
                </span>
              </div>

              {/* DỊCH VỤ */}
              <div className="sheet__sec">
                <span className="sheet__lbl">Dịch vụ</span>
                {full
                  ? (full.items || []).map((it) => (
                      <span className="sheet__svc" key={it.id}>{it.service_name} ×{toNumber(it.quantity)}</span>
                    ))
                  : <span className="sheet__svc sheet__muted">Đang tải…</span>}
              </div>

              {/* GHI CHÚ (tái dùng kiểu History) */}
              <div className="sheet__sec">
                <span className="sheet__lbl">Ghi chú</span>
                {note
                  ? <span className="hexp__note hexp__note--has">{note}</span>
                  : <span className="hexp__note hexp__note--empty">Không có ghi chú</span>}
              </div>

              {/* TIMELINE NGANG (tái dùng markup History 6.41-6.42) */}
              <div className="sheet__sec">
                <span className="sheet__lbl">Nhật ký thời gian</span>
                {full ? (
                  <div className="htl">
                    {buildTimeline(full).map((s, i) => (
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
                ) : <span className="sheet__svc sheet__muted">Đang tải…</span>}
              </div>

              {/* HÀNH ĐỘNG CHÍNH: ← lùi · → tiến (pay-first giữ nguyên) · In liên 2 */}
              <div className="sheet__main-acts">
                <button
                  className="sheet__move"
                  disabled={colIdx <= 0 || busyId === o.id}
                  onClick={() => { setSheet(null); move(o, 'back') }}
                  aria-label={colIdx > 0 ? `Lùi về ${COLUMNS[colIdx - 1].label}` : 'Lùi'}
                ><Icon name="arrow-left" className="sheet__move-ic" /></button>
                <button
                  className="sheet__move sheet__move--next"
                  disabled={busyId === o.id}
                  onClick={() => { setSheet(null); move(o, 'fwd') }}
                  aria-label={COLUMNS[colIdx + 1] ? `Sang ${COLUMNS[colIdx + 1].label}` : 'Giao đơn'}
                ><Icon name="arrow-right" className="sheet__move-ic" /></button>
                {full
                  ? <Lien2PrintButton order={full} className="sheet__lien2" />
                  : <button className="sheet__lien2" disabled>In liên 2</button>}
              </div>

              {/* HÀNH ĐỘNG PHỤ: In bill · Chi tiết · Thu tiền · Hủy · Đóng */}
              <div className="sheet__sub-acts">
                <button className="sheet__mini" onClick={() => { const id = o.id; setSheet(null); printBill(id) }}>In bill</button>
                <button className="sheet__mini" onClick={() => navigate(`/orders/${o.id}`)}>Chi tiết</button>
                <button className="sheet__mini" onClick={() => navigate(`/orders/${o.id}/pay`)}>Thu tiền</button>
                {CANCELLABLE.has(o.order_status) && (
                  <button className="sheet__mini sheet__mini--danger" onClick={() => { setSheet(null); setCancelModal(o) }}>Hủy đơn</button>
                )}
                <button className="sheet__mini" onClick={() => setSheet(null)}>Đóng</button>
              </div>
            </div>
          </div>
        )
      })()}

      {/* ── Popup HỦY ĐƠN (Stage 6.28): lý do bắt buộc + hoàn tiền → sổ luôn cân ── */}
      {cancelModal && (
        <CancelOrderModal
          order={cancelModal}
          onClose={() => setCancelModal(null)}
          onCancelled={(updated) => {
            setCancelModal(null)
            setToast({ msg: `Đã hủy đơn ${updated.order_code}` })
            load()
          }}
        />
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
              {[['cash', 'Tiền mặt'], ['transfer', 'Chuyển khoản']].map(([k, lbl]) => (
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
                  Ghi nợ (khách trả sau)
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
