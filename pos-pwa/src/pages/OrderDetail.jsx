import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import MoneyInput from '../components/MoneyInput'
import { ApiError, api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'
import {
  CANCELLABLE,
  NEXT_STATUS,
  ORDER_STATUS,
  PAYMENT_METHOD,
  PAYMENT_STATUS,
  TXN_TYPE,
} from '../lib/orders'

export default function OrderDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [order, setOrder] = useState(null)
  const [payments, setPayments] = useState([])
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)
  const [confirmCancel, setConfirmCancel] = useState(false)

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

  const ps = PAYMENT_STATUS[order.payment_status] || { label: order.payment_status, cls: '' }
  const paidSum = payments.reduce((s, p) => s + toNumber(p.amount), 0)
  const remaining = toNumber(order.total_amount) - paidSum
  const nextStatus = NEXT_STATUS[order.order_status]
  const canCancel = CANCELLABLE.has(order.order_status)
  // payment gốc để tham chiếu khi hoàn tiền (giao dịch dương gần nhất).
  const refundable = [...payments].reverse().find((p) => toNumber(p.amount) > 0)

  const advance = async () => {
    setBusy(true)
    setError('')
    try {
      await api.patch(`/orders/${id}/status`, { order_status: nextStatus })
      await load()
    } catch (err) {
      setError(err?.message || 'Không đổi được trạng thái')
    } finally {
      setBusy(false)
    }
  }

  const doCancel = async () => {
    setBusy(true)
    setError('')
    try {
      await api.del(`/orders/${id}`)
      setConfirmCancel(false)
      await load()
    } catch (err) {
      setError(err?.message || 'Không hủy được đơn')
    } finally {
      setBusy(false)
    }
  }

  const submitRefund = async () => {
    if (!refundReason.trim()) {
      setError('Nhập lý do hoàn tiền.')
      return
    }
    if (!refundable) {
      setError('Đơn chưa có giao dịch để hoàn.')
      return
    }
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
      setRefundStep('idle')
      setRefundAmount('')
      setRefundReason('')
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_OPEN_SHIFT') {
        setError('Cần mở ca trước khi hoàn tiền.')
      } else {
        setError(err?.message || 'Không hoàn được tiền')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="detail">
      <div className="card">
        <div className="detail__head">
          <span className="detail__code">{order.order_code}</span>
          <span className={`badge-ps ${ps.cls}`}>{ps.label}</span>
        </div>
        <dl className="kv">
          <div><dt>Trạng thái</dt><dd>{ORDER_STATUS[order.order_status]}</dd></div>
          <div><dt>Tổng tiền</dt><dd>{formatVND(order.total_amount)}</dd></div>
          <div><dt>Đã thu</dt><dd>{formatVND(paidSum)}</dd></div>
          {remaining > 0 && (
            <div><dt>Còn lại</dt><dd>{formatVND(remaining)}</dd></div>
          )}
          <div><dt>Khách</dt><dd>{order.customer_name || 'Khách lẻ'}</dd></div>
          <div><dt>Tạo lúc</dt><dd>{formatDateTime(order.created_at)} · {order.created_by_name}</dd></div>
        </dl>
      </div>

      <div className="card">
        <h3 className="card__title">Hạng mục</h3>
        {order.items.map((it) => (
          <div className="summary__row" key={it.id}>
            <span>{it.service_name} × {toNumber(it.quantity)}</span>
            <span>{formatVND(it.subtotal)}</span>
          </div>
        ))}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {/* Hành động trạng thái */}
      <div className="detail__actions">
        {order.payment_status !== 'paid' && order.order_status !== 'cancelled' && (
          <button
            className="btn btn--primary btn--lg btn--block"
            onClick={() => navigate(`/orders/${id}/pay`)}
          >
            💵 Thu tiền {remaining > 0 ? `(còn ${formatVND(remaining)})` : ''}
          </button>
        )}
        {nextStatus && (
          <button className="btn btn--primary btn--lg btn--block" onClick={advance} disabled={busy}>
            ➡️ Chuyển sang: {ORDER_STATUS[nextStatus]}
          </button>
        )}
        {canCancel &&
          (confirmCancel ? (
            <div className="confirm">
              <span>Hủy đơn này?</span>
              <div className="row-actions">
                <button className="btn btn--ghost" onClick={() => setConfirmCancel(false)}>
                  Không
                </button>
                <button className="btn btn--danger" onClick={doCancel} disabled={busy}>
                  Chắc chắn hủy
                </button>
              </div>
            </div>
          ) : (
            <button className="btn btn--ghost btn--block" onClick={() => setConfirmCancel(true)}>
              Hủy đơn
            </button>
          ))}
      </div>

      {/* Lịch sử dòng tiền */}
      <div className="card">
        <h3 className="card__title">Lịch sử thu/chi</h3>
        {payments.length === 0 ? (
          <p className="cart__empty">Chưa có giao dịch.</p>
        ) : (
          payments.map((p) => {
            const amt = toNumber(p.amount)
            return (
              <div className="pay-row" key={p.id}>
                <div className="pay-row__info">
                  <span className="pay-row__type">
                    {TXN_TYPE[p.transaction_type] || p.transaction_type} ·{' '}
                    {PAYMENT_METHOD[p.payment_method] || p.payment_method}
                  </span>
                  <span className="pay-row__meta">
                    {p.created_by_name} · {formatDateTime(p.created_at)}
                  </span>
                  {p.reason && <span className="pay-row__reason">{p.reason}</span>}
                </div>
                <span className={`pay-row__amt ${amt < 0 ? 'pay-row__amt--neg' : ''}`}>
                  {amt > 0 ? '+' : ''}
                  {formatVND(amt)}
                </span>
              </div>
            )
          })
        )}
      </div>

      {/* Hoàn tiền (2 bước) */}
      {paidSum > 0 && order.order_status !== 'cancelled' && (
        <div className="card">
          {refundStep === 'idle' && (
            <button className="btn btn--ghost btn--block" onClick={() => setRefundStep('form')}>
              ↩️ Hoàn tiền
            </button>
          )}
          {refundStep !== 'idle' && (
            <>
              <h3 className="card__title">Hoàn tiền</h3>
              <label className="field">
                <span>Số tiền hoàn</span>
                <MoneyInput value={refundAmount} onChange={setRefundAmount} />
              </label>
              <label className="field">
                <span>Lý do (bắt buộc)</span>
                <input
                  className="input"
                  type="text"
                  value={refundReason}
                  onChange={(e) => setRefundReason(e.target.value)}
                  placeholder="VD: khách trả hàng"
                />
              </label>
              {refundStep === 'form' ? (
                <div className="row-actions">
                  <button
                    className="btn btn--ghost"
                    onClick={() => {
                      setRefundStep('idle')
                      setError('')
                    }}
                  >
                    Hủy
                  </button>
                  <button
                    className="btn btn--primary"
                    onClick={() => {
                      if (!refundReason.trim() || toNumber(refundAmount) <= 0) {
                        setError('Nhập số tiền và lý do hoàn.')
                        return
                      }
                      setError('')
                      setRefundStep('confirm')
                    }}
                  >
                    Tiếp tục
                  </button>
                </div>
              ) : (
                <div className="confirm">
                  <span>
                    Xác nhận hoàn <strong>{formatVND(toNumber(refundAmount))}</strong>?
                  </span>
                  <div className="row-actions">
                    <button className="btn btn--ghost" onClick={() => setRefundStep('form')}>
                      Quay lại
                    </button>
                    <button className="btn btn--danger" onClick={submitRefund} disabled={busy}>
                      Chắc chắn hoàn
                    </button>
                  </div>
                </div>
              )}
            </>
          )}
        </div>
      )}
    </div>
  )
}
