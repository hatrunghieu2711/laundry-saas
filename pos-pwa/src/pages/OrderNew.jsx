import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'

// Bảng giá Giặt Ủi 2H — CỐ ĐỊNH, không phụ thu express. Dịch vụ: "Giặt sấy".
const TIERS = [
  { key: 'le3', label: '≤3kg', name: 'Giặt sấy ≤3kg', price: 60000 },
  { key: 'kg5', label: '5kg', name: 'Giặt sấy 5kg', price: 90000 },
  { key: 'kg7', label: '7kg', name: 'Giặt sấy 7kg', price: 120000 },
]
const PER_KG_PRICE = 18000 // >7kg: 18.000đ/kg

export default function OrderNew() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(isOwner ? null : user?.branch_id || null)
  const [shiftState, setShiftState] = useState('loading') // loading|open|none|needbranch
  const [cart, setCart] = useState([])
  const [kg, setKg] = useState('')
  const [phone, setPhone] = useState('')
  const [custName, setCustName] = useState('')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState(null)
  const idRef = useRef(0)

  useEffect(() => {
    if (!isOwner) return
    api
      .get('/branches?limit=200')
      .then((p) => {
        const active = p.items.filter((b) => b.status === 'active')
        setBranches(active)
        if (active.length === 1) setBranchId(active[0].id)
      })
      .catch(() => {})
  }, [isOwner])

  const checkShift = useCallback(async () => {
    setError('')
    if (isOwner && !branchId) {
      setShiftState('needbranch')
      return
    }
    setShiftState('loading')
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      await api.get(`/shifts/current${q}`)
      setShiftState('open')
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) setShiftState('none')
      else {
        setShiftState('none')
        setError(err?.message || '')
      }
    }
  }, [isOwner, branchId])

  useEffect(() => {
    checkShift()
  }, [checkShift])

  // ── thao tác giỏ ──
  const addTier = (tier) => {
    setCart((prev) => {
      const i = prev.findIndex((x) => x.tierKey === tier.key)
      if (i >= 0) {
        const next = [...prev]
        next[i] = { ...next[i], quantity: next[i].quantity + 1 }
        return next
      }
      idRef.current += 1
      return [
        ...prev,
        {
          id: idRef.current,
          tierKey: tier.key,
          service_name: tier.name,
          quantity: 1,
          unit_price: tier.price,
        },
      ]
    })
  }

  const addPerKg = () => {
    const k = toNumber(kg)
    if (k <= 0) return
    idRef.current += 1
    setCart((prev) => [
      ...prev,
      {
        id: idRef.current,
        tierKey: null,
        service_name: `Giặt sấy ${k}kg`,
        quantity: k,
        unit_price: PER_KG_PRICE,
      },
    ])
    setKg('')
  }

  const bump = (id, delta) =>
    setCart((prev) =>
      prev
        .map((x) => (x.id === id ? { ...x, quantity: x.quantity + delta } : x))
        .filter((x) => x.quantity > 0),
    )
  const removeItem = (id) => setCart((prev) => prev.filter((x) => x.id !== id))

  const total = cart.reduce((s, i) => s + i.quantity * i.unit_price, 0)

  const submit = async () => {
    if (cart.length === 0) return
    setBusy(true)
    setError('')
    try {
      let customerId
      const ph = phone.trim()
      if (ph) {
        const found = await api.get(`/customers?phone=${encodeURIComponent(ph)}&limit=1`)
        if (found.total > 0) customerId = found.items[0].id
        else {
          const c = await api.post('/customers', {
            phone: ph,
            full_name: custName.trim() || undefined,
          })
          customerId = c.id
        }
      }
      const body = {
        items: cart.map(({ service_name, quantity, unit_price }) => ({
          service_name,
          quantity,
          unit_price,
        })),
      }
      if (customerId) body.customer_id = customerId
      if (isOwner) body.branch_id = branchId
      const order = await api.post('/orders', body)
      setCreated(order)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_OPEN_SHIFT') {
        setError('Chi nhánh chưa có ca mở.')
      } else {
        setError(err?.message || 'Không tạo được đơn, thử lại.')
      }
    } finally {
      setBusy(false)
    }
  }

  const startNew = () => {
    setCreated(null)
    setCart([])
    setPhone('')
    setCustName('')
    setKg('')
    setError('')
  }

  // ── màn kết quả tạo đơn ──
  if (created) {
    return (
      <div className="ordernew">
        <div className="created">
          <p className="created__hint">Đã tạo đơn — ghi mã lên đồ/phiếu:</p>
          <div className="created__code">{created.order_code}</div>
          <div className="created__total">{formatVND(created.total_amount)}</div>
          <button
            className="btn btn--primary btn--xl btn--block"
            onClick={() => navigate(`/orders/${created.id}/pay`)}
          >
            💵 Thu tiền ngay
          </button>
          <button className="btn btn--ghost btn--lg btn--block" onClick={startNew}>
            ＋ Tạo đơn mới
          </button>
        </div>
      </div>
    )
  }

  // ── chặn khi chưa có ca ──
  if (shiftState === 'loading') return <p className="shift__hint">Đang kiểm tra ca…</p>

  const branchPicker = isOwner && (
    <div className="branch-picker">
      <span className="branch-picker__label">Chi nhánh</span>
      <div className="branch-picker__chips">
        {branches.map((b) => (
          <button
            key={b.id}
            className={`chip ${branchId === b.id ? 'chip--active' : ''}`}
            onClick={() => setBranchId(b.id)}
          >
            {b.code} · {b.name}
          </button>
        ))}
      </div>
    </div>
  )

  if (shiftState === 'needbranch') {
    return (
      <div className="ordernew">
        {branchPicker}
        <p className="shift__hint">Chọn chi nhánh để tạo đơn.</p>
      </div>
    )
  }

  if (shiftState === 'none') {
    return (
      <div className="ordernew">
        {branchPicker}
        <div className="shift__empty">
          <div className="shift__empty-icon">🕒</div>
          <p>Cần mở ca trước khi tạo đơn.</p>
          <button className="btn btn--primary btn--xl btn--block" onClick={() => navigate('/')}>
            Về màn ca
          </button>
        </div>
      </div>
    )
  }

  // ── builder (ca đang mở) ──
  return (
    <div className="ordernew">
      {branchPicker}
      {error && <div className="alert alert--error">{error}</div>}

      <div className="pricing-grid">
        {TIERS.map((t) => (
          <button key={t.key} className="tier-btn" onClick={() => addTier(t)}>
            <span className="tier-btn__label">{t.label}</span>
            <span className="tier-btn__price">{formatVND(t.price)}</span>
          </button>
        ))}
      </div>

      <div className="perkg">
        <span className="perkg__label">&gt;7kg — {formatVND(PER_KG_PRICE)}/kg</span>
        <div className="perkg__row">
          <input
            className="input"
            type="number"
            inputMode="decimal"
            min="0"
            step="0.5"
            placeholder="Số kg"
            value={kg}
            onChange={(e) => setKg(e.target.value)}
          />
          <button className="btn btn--ghost btn--lg" onClick={addPerKg} disabled={toNumber(kg) <= 0}>
            ＋ Thêm
          </button>
        </div>
      </div>

      <div className="cart">
        {cart.length === 0 ? (
          <p className="cart__empty">Bấm mức cân ở trên để thêm vào đơn.</p>
        ) : (
          cart.map((i) => (
            <div className="cart__item" key={i.id}>
              <div className="cart__info">
                <span className="cart__name">{i.service_name}</span>
                <span className="cart__line">
                  {i.quantity} × {formatVND(i.unit_price)} ={' '}
                  <strong>{formatVND(i.quantity * i.unit_price)}</strong>
                </span>
              </div>
              <div className="cart__qty">
                <button className="qty-btn" onClick={() => bump(i.id, -1)}>
                  −
                </button>
                <span className="qty-val">{i.quantity}</span>
                <button className="qty-btn" onClick={() => bump(i.id, +1)}>
                  ＋
                </button>
                <button className="qty-btn qty-btn--del" onClick={() => removeItem(i.id)}>
                  ✕
                </button>
              </div>
            </div>
          ))
        )}
      </div>

      <details className="customer">
        <summary>Khách hàng (tùy chọn)</summary>
        <div className="customer__fields">
          <input
            className="input"
            type="tel"
            inputMode="numeric"
            placeholder="Số điện thoại"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
          />
          <input
            className="input"
            type="text"
            placeholder="Tên (nếu khách mới)"
            value={custName}
            onChange={(e) => setCustName(e.target.value)}
          />
        </div>
      </details>

      <div className="order-bar">
        <div className="order-bar__total">
          <span>Tổng</span>
          <strong>{formatVND(total)}</strong>
        </div>
        <button
          className="btn btn--primary btn--xl btn--block"
          onClick={submit}
          disabled={busy || cart.length === 0}
        >
          {busy ? 'Đang tạo…' : 'TẠO ĐƠN'}
        </button>
      </div>
    </div>
  )
}
