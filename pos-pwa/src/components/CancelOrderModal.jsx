import { useEffect, useState } from 'react'
import MoneyInput from './MoneyInput'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'

// Popup HỦY ĐƠN (Stage 6.28; style mới `.panel` — Stage 6.29) — dùng chung OrderDetail + Board.
// Lý do BẮT BUỘC; nếu đơn ĐÃ THU → ô "Hoàn cho khách" (0..đã thu, mặc định = đã thu) + "Giữ
// lại". Hoàn tiền mặt ra két. Tự fetch số đã thu (net payments). Overlay neo-TRÊN + body cuộn
// → ô nhập KHÔNG bị bàn phím ảo che (Sunmi màn ngang). POST /orders/{id}/cancel.
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
  // Nhắc tách đơn: CHƯA thu nhưng đã LÀM DỞ (washing/drying/ready) → nên hủy + tạo đơn mới
  // cho phần đã làm để thu đúng. KHÔNG hiện ở đơn 'created' (chưa làm) hay đơn đã thu.
  const startedUnpaid = paidSum != null && !hasPaid && order.order_status !== 'created'

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
    <div className="modal-overlay modal-overlay--top" role="dialog" aria-modal="true">
      <div className="panel panel--modal">
        <div className="panel__head">
          <span className="panel__title">Hủy đơn {order.order_code}</span>
        </div>

        <div className="panel__body">
          <div className="panel__group">
            <p className="panel__hint panel__hint--danger">Hủy đơn KHÔNG hoàn tác được.</p>

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

            {startedUnpaid && (
              <p className="panel__hint">
                Nếu đã dùng một phần dịch vụ (vd đã giặt chưa sấy), hãy hủy đơn này rồi
                TẠO ĐƠN MỚI cho phần đã làm để thu tiền đúng.
              </p>
            )}

            {paidSum == null ? (
              <p className="panel__row">Đang tải số đã thu…</p>
            ) : (
              hasPaid && (
                <>
                  <div className="panel__row">
                    <span>Đã thu</span>
                    <b>{formatVND(paidSum)}</b>
                  </div>
                  <label className="field">
                    <span>Hoàn cho khách (tiền mặt)</span>
                    <MoneyInput value={refund} onChange={setRefund} />
                  </label>
                  <div className="panel__row panel__row--strong">
                    <span>Giữ lại</span>
                    <b>{formatVND(Math.max(0, kept))}</b>
                  </div>
                </>
              )
            )}

            {error && <div className="alert alert--error">{error}</div>}
          </div>
        </div>

        <div className="panel__foot">
          <button className="btn btn--ghost" onClick={onClose} disabled={busy}>
            Đóng
          </button>
          <button
            className="btn btn--danger"
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
