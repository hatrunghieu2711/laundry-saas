import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import MoneyInput from '../components/MoneyInput'
import Receipt from '../components/Receipt'
import ShiftEmpty from '../components/ShiftEmpty'
import { setPrintMode } from '../lib/printQueue'
import { nativePrintActive } from '../lib/platform'
import { nativePrintBill } from '../lib/nativePrintStore'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'
import { PAYMENT_METHOD } from '../lib/orders'

const METHODS = ['cash', 'transfer', 'qr', 'cod']

export default function OrderPay() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [order, setOrder] = useState(null)
  const [paidSum, setPaidSum] = useState(0)
  const [hasShift, setHasShift] = useState(null) // null=đang kiểm tra
  const [method, setMethod] = useState('cash')
  const [amount, setAmount] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')

  const load = useCallback(async () => {
    setError('')
    try {
      const o = await api.get(`/orders/${id}`)
      setOrder(o)
      const pays = await api.get(`/payments?order_id=${id}&limit=200`)
      const sum = pays.items.reduce((s, p) => s + toNumber(p.amount), 0)
      setPaidSum(sum)
      const remain = toNumber(o.total_amount) - sum
      setAmount(remain > 0 ? remain : '')
      // Kiểm tra ca mở tại branch của đơn.
      try {
        await api.get(`/shifts/current?branch_id=${o.branch_id}`)
        setHasShift(true)
      } catch (err) {
        setHasShift(err?.status === 404 ? false : true)
      }
    } catch (err) {
      setError(err?.message || 'Không tải được đơn')
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  if (!order) return <p className="shift__hint">Đang tải…</p>

  const remaining = toNumber(order.total_amount) - paidSum
  const paidEnough = remaining <= 0

  const pay = async (transactionType) => {
    setBusy(true)
    setError('')
    try {
      await api.post('/payments', {
        order_id: id,
        amount: transactionType === 'debt' ? 0 : toNumber(amount),
        payment_method: method,
        transaction_type: transactionType,
      })
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_OPEN_SHIFT') {
        setError('Cần mở ca trước khi thu tiền.')
        setHasShift(false)
      } else if (err instanceof ApiError && err.code === 'INVALID_AMOUNT') {
        setError('Số tiền phải lớn hơn 0.')
      } else {
        setError(err?.message || 'Không ghi nhận được giao dịch')
      }
    } finally {
      setBusy(false)
    }
  }

  if (hasShift === false) {
    return (
      <div className="pay">
        <ShiftEmpty>
          <p>Cần mở ca trước khi thu tiền.</p>
          <button className="btn btn--primary btn--xl btn--block" onClick={() => navigate('/')}>
            Về màn ca
          </button>
        </ShiftEmpty>
      </div>
    )
  }

  return (
    <div className="pay">
      <div className="pay__card">
        <span className="pay__code">{order.order_code}</span>
        <div className="pay-amounts">
          <div><span>Tổng đơn</span><strong>{formatVND(order.total_amount)}</strong></div>
          <div><span>Đã thu</span><strong className="pay__amt-ok">{formatVND(paidSum)}</strong></div>
          <div className="pay-amounts__remain">
            <span>Còn lại</span>
            <strong className={remaining > 0 ? 'pay__amt-due' : ''}>{formatVND(remaining > 0 ? remaining : 0)}</strong>
          </div>
        </div>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {paidEnough ? (
        <div className="pay__card pay__done">
          <span className="pay__done-row">
            <svg className="pay__check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>
            Đơn đã thu đủ.
          </span>
          <button
            className="btn btn--primary btn--xl btn--block"
            onClick={() => navigate(`/orders/${id}`)}
          >
            Đổi trạng thái đơn
          </button>
          {/* Khách đã cầm bill cũ "CHƯA THANH TOÁN" → in tờ mới (Receipt đọc data hiện tại = paid). */}
          <button
            className="btn btn--ghost btn--lg btn--block"
            style={{ marginTop: 10 }}
            onClick={() => { if (nativePrintActive()) nativePrintBill(order); else { setPrintMode('bill'); window.print() } }}
          >
            In lại bill
          </button>
        </div>
      ) : (
        <div className="pay__card">
          <span className="field-label">Phương thức</span>
          <div className="method-grid">
            {METHODS.map((m) => (
              <button
                key={m}
                className={`method-btn ${method === m ? 'method-btn--active' : ''}`}
                onClick={() => setMethod(m)}
              >
                {PAYMENT_METHOD[m]}
              </button>
            ))}
          </div>

          <label className="field" style={{ marginTop: 14 }}>
            <span>Số tiền thu</span>
            <MoneyInput value={amount} onChange={setAmount} />
          </label>

          <button
            className="btn btn--primary btn--xl btn--block"
            onClick={() => pay('payment')}
            disabled={busy || toNumber(amount) <= 0}
          >
            {busy ? 'Đang ghi…' : 'XÁC NHẬN THU'}
          </button>
          <button
            className="btn btn--ghost btn--lg btn--block"
            style={{ marginTop: 10 }}
            onClick={() => pay('debt')}
            disabled={busy}
          >
            GHI NỢ (khách thanh toán sau)
          </button>
        </div>
      )}

      {/* Bill ẩn (in lại) — @media print hiện .print-receipt, ẩn #root. Đọc order hiện tại. */}
      <Receipt order={order} />
    </div>
  )
}
