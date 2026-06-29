import { Fragment, useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import CancelOrderModal from '../components/CancelOrderModal'
import MoneyInput from '../components/MoneyInput'
import Receipt from '../components/Receipt'
import { setPrintMode } from '../lib/printQueue'
import { nativePrintActive } from '../lib/platform'
import { nativePrintBill } from '../lib/nativePrintStore'
import { ApiError, api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'
import { formatPickupBoard, formatPickupShort } from '../lib/datetime'
import { CANCELLABLE, ORDER_STATUS, PAYMENT_METHOD, TXN_TYPE } from '../lib/orders'
import { buildTimeline } from '../lib/timeline'

// Badge trạng thái (tái dùng .hbadge--* của tab Lịch sử): hủy đỏ / giao xanh / mới amber / xử lý cam.
function statusBadge(os) {
  if (os === 'cancelled') return { label: ORDER_STATUS[os] || 'Đã hủy', cls: 'hbadge--cancel' }
  if (os === 'delivered' || os === 'completed') return { label: ORDER_STATUS[os] || 'Đã giao', cls: 'hbadge--done' }
  if (os === 'created') return { label: ORDER_STATUS[os] || 'Mới tạo', cls: 'hbadge--new' }
  return { label: ORDER_STATUS[os] || os, cls: 'hbadge--proc' }
}

// Trang chi tiết đơn (Stage 6.51 redesign): 2 cột, style mới, KHÔNG emoji. Chuyển trạng thái
// đã chuyển về Board/sheet → màn này BỎ nút "Chuyển sang" + pay-first popup (an toàn: không còn
// đường giao hàng nào khác ở đây). Giữ nguyên: hoàn tiền, hủy đơn, in bill, mọi tính toán tiền.
export default function OrderDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [order, setOrder] = useState(null)
  const [payments, setPayments] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [cancelModal, setCancelModal] = useState(false)

  // refund: idle -> form -> confirm
  const [refundStep, setRefundStep] = useState('idle')
  const [refundAmount, setRefundAmount] = useState('')
  const [refundReason, setRefundReason] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const o = await api.get(`/orders/${id}`)
      setOrder(o)
      const pays = await api.get(`/payments?order_id=${id}&limit=200`)
      setPayments(pays.items)
    } catch (err) {
      setError(err?.message || 'Không tải được đơn')
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  if (error && !order) return <div className="alert alert--error">{error}</div>
  if (!order) return <p className="shift__hint">Đang tải đơn…</p>

  const paid = order.payment_status === 'paid'
  const sb = statusBadge(order.order_status)
  const paidSum = payments.reduce((s, p) => s + toNumber(p.amount), 0)
  const remaining = toNumber(order.total_amount) - paidSum
  const canCancel = CANCELLABLE.has(order.order_status)
  const note = (order.notes || '').trim()
  const surcharge = toNumber(order.surcharge_amount)
  const discount = toNumber(order.discount_amount)
  const canRefund = paidSum > 0 && order.order_status !== 'cancelled'
  // payment gốc để tham chiếu khi hoàn tiền (giao dịch dương gần nhất).
  const refundable = [...payments].reverse().find((p) => toNumber(p.amount) > 0)

  const submitRefund = async () => {
    if (!refundReason.trim()) { setError('Nhập lý do hoàn tiền.'); return }
    if (!refundable) { setError('Đơn chưa có giao dịch để hoàn.'); return }
    setBusy(true)
    setError('')
    try {
      await api.post('/payments/refund', {
        order_id: id,
        amount: toNumber(refundAmount),
        payment_method: 'cash',
        reason: refundReason.trim(),
        reference_payment_id: refundable.id,
      })
      setRefundStep('idle'); setRefundAmount(''); setRefundReason('')
      await load()
    } catch (err) {
      setError(err instanceof ApiError && err.code === 'NO_OPEN_SHIFT'
        ? 'Cần mở ca trước khi hoàn tiền.' : (err?.message || 'Không hoàn được tiền'))
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="od">
      {/* HEADER */}
      <div className="od__hd">
        <div className="od__hd-l">
          <span className="od__code">{order.order_code}</span>
          <span className={`od__pay ${paid ? 'is-ok' : 'is-due'}`}>{paid ? 'Đã thu' : 'Chưa thu'}</span>
          <span className={`hbadge ${sb.cls}`}>{sb.label}</span>
        </div>
        <div className="od__hd-r">
          <button className="od__nav" onClick={() => navigate('/orders/new')}>Tạo đơn</button>
          <button className="od__nav" onClick={() => navigate('/history')}>Lịch sử</button>
          <button className="od__nav" onClick={() => navigate('/board')}>Đơn hàng</button>
        </div>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {/* 2 CỘT (màn hẹp → 1 cột) */}
      <div className="od__cols">
        {/* CỘT TRÁI */}
        <div className="od__col">
          <div className="od__card">
            <h3 className="od__card-title">Thông tin</h3>
            <dl className="od__kv">
              <div><dt>Khách</dt><dd>{order.customer_name || 'Khách lẻ'}</dd></div>
              <div><dt>SĐT</dt><dd>{order.customer_phone || '—'}</dd></div>
              {order.pickup_at && <div><dt>Hẹn lấy</dt><dd>{formatPickupShort(order.pickup_at)}</dd></div>}
              <div><dt>Tạo lúc</dt><dd>{formatDateTime(order.created_at)} · {order.created_by_name}</dd></div>
            </dl>
            <div className="od__note-wrap">
              {note
                ? <span className="hexp__note hexp__note--has">{note}</span>
                : <span className="hexp__note hexp__note--empty">Không có ghi chú</span>}
            </div>
          </div>

          <div className="od__card">
            <h3 className="od__card-title">Hạng mục</h3>
            {order.items.map((it) => (
              <div className="od__line" key={it.id}>
                <span className="od__line-l">{it.service_name} × {toNumber(it.quantity)}</span>
                <span className="od__line-r">{formatVND(it.subtotal)}</span>
              </div>
            ))}
            {(surcharge > 0 || discount > 0) && (
              <div className="od__line od__line--sub">
                <span className="od__line-l">Tạm tính</span>
                <span className="od__line-r">{formatVND(order.subtotal)}</span>
              </div>
            )}
            {surcharge > 0 && (
              <div className="od__line od__line--sub">
                <span className="od__line-l">{order.surcharge_reason || 'Phụ thu'}</span>
                <span className="od__line-r">+{formatVND(surcharge)}</span>
              </div>
            )}
            {discount > 0 && (
              <div className="od__line od__line--sub">
                <span className="od__line-l">{order.discount_reason || 'Giảm giá'}</span>
                <span className="od__line-r">−{formatVND(discount)}</span>
              </div>
            )}
            <div className="od__line od__line--total">
              <span className="od__line-l">Tổng</span>
              <span className="od__line-r">{formatVND(order.total_amount)}</span>
            </div>
          </div>
        </div>

        {/* CỘT PHẢI */}
        <div className="od__col">
          <div className="od__metrics">
            <div className="od__metric">
              <span className="od__metric-lbl">Đã thu</span>
              <span className="od__metric-val is-ok">{formatVND(paidSum)}</span>
            </div>
            <div className="od__metric">
              <span className="od__metric-lbl">Còn lại</span>
              <span className={`od__metric-val ${remaining > 0 ? 'is-due' : ''}`}>{formatVND(remaining > 0 ? remaining : 0)}</span>
            </div>
          </div>

          <div className="od__card">
            <h3 className="od__card-title">Tiến trình</h3>
            <div className="htl">
              {buildTimeline(order).map((s, i) => (
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

          <div className="od__card">
            <h3 className="od__card-title">Lịch sử thu/chi</h3>
            {payments.length === 0 ? (
              <p className="od__empty">Chưa có giao dịch.</p>
            ) : (
              payments.map((p) => {
                const amt = toNumber(p.amount)
                return (
                  <div className="od__pay-row" key={p.id}>
                    <div className="od__pay-info">
                      <span className="od__pay-type">
                        {TXN_TYPE[p.transaction_type] || p.transaction_type} · {PAYMENT_METHOD[p.payment_method] || p.payment_method}
                      </span>
                      <span className="od__pay-meta">{p.created_by_name} · {formatDateTime(p.created_at)}</span>
                      {p.reason && <span className="od__pay-reason">{p.reason}</span>}
                    </div>
                    <span className={`od__pay-amt ${amt < 0 ? 'is-neg' : ''}`}>
                      {amt > 0 ? '+' : ''}{formatVND(amt)}
                    </span>
                  </div>
                )
              })
            )}
          </div>
        </div>
      </div>

      {/* HOÀN TIỀN — form 2 bước (giữ logic), hiện khi đã mở */}
      {canRefund && refundStep !== 'idle' && (
        <div className="od__card od__refund">
          <h3 className="od__card-title">Hoàn tiền</h3>
          <label className="field">
            <span>Số tiền hoàn</span>
            <MoneyInput value={refundAmount} onChange={setRefundAmount} />
          </label>
          <label className="field">
            <span>Lý do (bắt buộc)</span>
            <input className="input" type="text" value={refundReason}
              onChange={(e) => setRefundReason(e.target.value)} placeholder="VD: khách trả hàng" />
          </label>
          {refundStep === 'form' ? (
            <div className="od__row-actions">
              <button className="btn btn--ghost" onClick={() => { setRefundStep('idle'); setError('') }}>Hủy</button>
              <button className="btn btn--primary" onClick={() => {
                if (!refundReason.trim() || toNumber(refundAmount) <= 0) { setError('Nhập số tiền và lý do hoàn.'); return }
                setError(''); setRefundStep('confirm')
              }}>Tiếp tục</button>
            </div>
          ) : (
            <div className="od__confirm">
              <span>Xác nhận hoàn <strong>{formatVND(toNumber(refundAmount))}</strong>?</span>
              <div className="od__row-actions">
                <button className="btn btn--ghost" onClick={() => setRefundStep('form')}>Quay lại</button>
                <button className="btn btn--danger" onClick={submitRefund} disabled={busy}>Chắc chắn hoàn</button>
              </div>
            </div>
          )}
        </div>
      )}

      {/* DÒNG HÀNH ĐỘNG (ngang 2 cột) */}
      <div className="od__actions">
        <div className="od__actions-l">
          <button className="od__act" onClick={() => { if (nativePrintActive()) nativePrintBill(order); else { setPrintMode('bill'); window.print() } }}>In lại bill</button>
          {order.payment_status !== 'paid' && order.order_status !== 'cancelled' && (
            <button className="od__act od__act--primary" onClick={() => navigate(`/orders/${id}/pay`)}>
              Thu tiền{remaining > 0 ? ` (còn ${formatVND(remaining)})` : ''}
            </button>
          )}
        </div>
        <div className="od__actions-r">
          {canRefund && refundStep === 'idle' && (
            <button className="od__act od__act--info" onClick={() => setRefundStep('form')}>Hoàn tiền</button>
          )}
          {canCancel && (
            <button className="od__act od__act--danger" onClick={() => setCancelModal(true)}>Hủy đơn</button>
          )}
        </div>
      </div>

      {cancelModal && (
        <CancelOrderModal
          order={order}
          onClose={() => setCancelModal(false)}
          onCancelled={() => { setCancelModal(false); load() }}
        />
      )}

      <Receipt order={order} paid={paidSum} />
    </div>
  )
}
