import { useEffect, useState } from 'react'
import MoneyInput from './MoneyInput'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'

// Popup HỦY ĐƠN (Stage 6.28) — dùng chung OrderDetail + Board. Lý do BẮT BUỘC; nếu đơn ĐÃ
// THU thì cho nhập "Hoàn cho khách" (0..đã thu, mặc định = đã thu) và hiện "Giữ lại". Hoàn
// tiền mặt ra két. Tự fetch số đã thu (net payments) để tính — caller chỉ cần truyền order
// {id, order_code}. POST /orders/{id}/cancel {cancel_reason, refund_amount}.
export default function CancelOrderModal({ order, onClose, onCancelled }) {
  const [paidSum, setPaidSum] = useState(null) // null = đang tải
  const [reason, setReason] = useState('')
  const [refund, setRefund] = useState('')
  const [refundInit, setRefundInit] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  useEffect(() => {
    let alive = true
    api
      .get(`/payments?order_id=${order.id}&limit=200`)
      .then((r) => {
        if (alive) setPaidSum(r.items.reduce((s, p) => s + toNumber(p.amount), 0))
      })
      .catch(() => {
        if (alive) setPaidSum(0)
      })
    return () => {
      alive = false
    }
  }, [order.id])

  // Gợi ý hoàn tất cả khi biết số đã thu.
  useEffect(() => {
    if (paidSum != null && !refundInit) {
      setRefund(paidSum > 0 ? String(paidSum) : '0')
      setRefundInit(true)
    }
  }, [paidSum, refundInit])

  const hasPaid = (paidSum || 0) > 0
  const refundNum = toNumber(refund)
  const kept = (paidSum || 0) - refundNum

  const submit = async () => {
    if (!reason.trim()) {
      setError('Nhập lý do hủy.')
      return
    }
    if (hasPaid && (refundNum < 0 || refundNum > paidSum)) {
      setError(`Hoàn phải từ 0 đến ${formatVND(paidSum)}.`)
      return
    }
    setBusy(true)
    setError('')
    try {
      const updated = await api.post(`/orders/${order.id}/cancel`, {
        cancel_reason: reason.trim(),
        refund_amount: hasPaid ? refundNum : 0,
      })
      onCancelled?.(updated)
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'Hủy đơn thất bại')
      setBusy(false)
    }
  }

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal">
        <h3 className="modal__title">Hủy đơn {order.order_code}</h3>
        <p className="pay-dismiss">⚠️ Hủy đơn KHÔNG hoàn tác được.</p>

        <label className="field">
          <span>Lý do hủy (bắt buộc)</span>
          <input
            className="input"
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            placeholder="VD: khách đổi ý"
            autoFocus
          />
        </label>

        {paidSum == null ? (
          <p className="shift__hint">Đang tải số đã thu…</p>
        ) : (
          hasPaid && (
            <>
              <div className="pay-due">
                Đã thu: <b>{formatVND(paidSum)}</b>
              </div>
              <label className="field">
                <span>Hoàn cho khách (tiền mặt)</span>
                <MoneyInput value={refund} onChange={setRefund} />
              </label>
              <div className="pay-due">
                Giữ lại: <b>{formatVND(Math.max(0, kept))}</b>
              </div>
            </>
          )
        )}

        {error && <div className="alert alert--error">{error}</div>}

        <div className="modal__actions">
          <button className="btn btn--ghost btn--lg btn--block" onClick={onClose} disabled={busy}>
            Đóng
          </button>
          <button
            className="btn btn--danger btn--lg btn--block"
            onClick={submit}
            disabled={busy || paidSum == null}
          >
            {busy ? 'Đang hủy…' : 'Xác nhận hủy'}
          </button>
        </div>
      </div>
    </div>
  )
}
