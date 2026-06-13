import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Receipt from '../components/Receipt'
import WheelTimePicker from '../components/WheelTimePicker'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'
import { defaultPickup } from '../lib/datetime'
import { UNIT_LABEL, normalizeService } from '../lib/services'

// Bảng giá nạp ĐỘNG từ GET /services (kèm tiers). Không còn hardcode mức cân.
// Gửi service_id khi tạo đơn để backend snapshot giá đúng.
export default function OrderNew() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'
  const canManage = user?.role === 'owner' || user?.role === 'manager'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(isOwner ? null : user?.branch_id || null)
  const [shiftState, setShiftState] = useState('loading') // loading|open|none|needbranch
  const [services, setServices] = useState([])
  const [svcLoading, setSvcLoading] = useState(true)
  const [search, setSearch] = useState('')
  const [cart, setCart] = useState([])
  const [overflowKg, setOverflowKg] = useState({}) // { [tierId]: '2.5' } buffer ô nhập kg
  const [phone, setPhone] = useState('')
  const [custName, setCustName] = useState('')
  const [note, setNote] = useState('')
  const [pickup, setPickup] = useState(() => defaultPickup()) // giờ hẹn giao (Date)
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

  // Bảng giá tenant-scoped — nạp một lần.
  useEffect(() => {
    setSvcLoading(true)
    api
      .get('/services?limit=200')
      .then((p) => setServices(p.items.map(normalizeService)))
      .catch(() => setServices([]))
      .finally(() => setSvcLoading(false))
  }, [])

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
  const newId = () => {
    idRef.current += 1
    return idRef.current
  }

  const addPerUnit = (svc) => {
    setCart((prev) => {
      const i = prev.findIndex((x) => x.kind === 'per_unit' && x.service_id === svc.id)
      if (i >= 0) {
        const n = [...prev]
        n[i] = { ...n[i], quantity: n[i].quantity + 1 }
        return n
      }
      return [
        ...prev,
        {
          id: newId(),
          kind: 'per_unit',
          service_id: svc.id,
          name: svc.name,
          unit: svc.unit,
          unit_price: svc.unit_price,
          quantity: 1,
        },
      ]
    })
  }

  const addFlat = (svc, tier) => {
    setCart((prev) => {
      const i = prev.findIndex((x) => x.kind === 'flat' && x.tier_id === tier.id)
      if (i >= 0) {
        const n = [...prev]
        n[i] = { ...n[i], count: n[i].count + 1 }
        return n
      }
      return [
        ...prev,
        {
          id: newId(),
          kind: 'flat',
          service_id: svc.id,
          tier_id: tier.id,
          name: `${svc.name} (${tier.label})`,
          price: tier.price,
          weight: tier.max_value ?? 0, // gửi lên = ngưỡng bậc → backend khớp đúng bậc
          count: 1,
        },
      ]
    })
  }

  const addOverflow = (svc, tier) => {
    const kg = toNumber(overflowKg[tier.id])
    if (kg <= 0) return
    setCart((prev) => [
      ...prev,
      {
        id: newId(),
        kind: 'overflow',
        service_id: svc.id,
        name: `${svc.name} (${tier.label})`,
        unit_price: tier.price,
        quantity: kg,
      },
    ])
    setOverflowKg((m) => ({ ...m, [tier.id]: '' }))
  }

  const bump = (id, delta) =>
    setCart((prev) =>
      prev
        .map((x) => {
          if (x.id !== id) return x
          if (x.kind === 'flat') return { ...x, count: x.count + delta }
          return { ...x, quantity: x.quantity + delta }
        })
        .filter((x) => (x.kind === 'flat' ? x.count > 0 : x.quantity > 0)),
    )
  const removeItem = (id) => setCart((prev) => prev.filter((x) => x.id !== id))

  const lineTotal = (x) => (x.kind === 'flat' ? x.count * x.price : x.quantity * x.unit_price)
  const total = cart.reduce((s, x) => s + lineTotal(x), 0)

  // Mở rộng giỏ → items gửi backend: bậc trọn gói lặp `count` dòng (mỗi dòng 1 gói).
  const buildItems = () => {
    const items = []
    for (const x of cart) {
      if (x.kind === 'flat') {
        for (let k = 0; k < x.count; k += 1) items.push({ service_id: x.service_id, quantity: x.weight })
      } else {
        items.push({ service_id: x.service_id, quantity: x.quantity })
      }
    }
    return items
  }

  // Lọc nhanh theo tên dịch vụ.
  const visible = useMemo(() => {
    const q = search.trim().toLowerCase()
    return q ? services.filter((s) => s.name.toLowerCase().includes(q)) : services
  }, [services, search])
  const tierServices = visible.filter((s) => s.pricing_type === 'tier')
  const perUnitServices = visible.filter((s) => s.pricing_type === 'per_unit')

  const submit = async () => {
    if (cart.length === 0) return
    if (pickup.getTime() <= Date.now()) {
      setError('Không thể hẹn giờ giao trong quá khứ. Chọn lại giờ giao.')
      return
    }
    setBusy(true)
    setError('')
    try {
      let customerId
      const ph = phone.trim()
      if (ph) {
        const found = await api.get(`/customers?phone=${encodeURIComponent(ph)}&limit=1`)
        if (found.total > 0) customerId = found.items[0].id
        else {
          const c = await api.post('/customers', { phone: ph, full_name: custName.trim() || undefined })
          customerId = c.id
        }
      }
      const body = { items: buildItems(), pickup_at: pickup.toISOString() }
      if (customerId) body.customer_id = customerId
      if (note.trim()) body.notes = note.trim()
      if (isOwner) body.branch_id = branchId
      const order = await api.post('/orders', body)
      setCreated(order)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_OPEN_SHIFT') {
        setError('Chi nhánh chưa có ca mở.')
      } else if (err instanceof ApiError && err.code === 'PICKUP_AT_IN_PAST') {
        setError('Không thể hẹn giờ giao trong quá khứ. Chọn lại giờ giao.')
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
    setNote('')
    setOverflowKg({})
    setSearch('')
    setError('')
    setPickup(defaultPickup())
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
          <button className="btn btn--ghost btn--lg btn--block" onClick={() => window.print()}>
            🖨️ IN PHIẾU
          </button>
          <button className="btn btn--ghost btn--lg btn--block" onClick={startNew}>
            ＋ Tạo đơn mới
          </button>
        </div>
        {/* Đơn vừa tạo: chưa thu tiền → paid = 0 */}
        <Receipt order={created} paid={0} />
      </div>
    )
  }

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

      <div className="ordernew__grid">
        <div className="ordernew__main">
          <input
            className="input ordernew__search"
            type="search"
            placeholder="🔍 Tìm dịch vụ…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />

          {svcLoading ? (
            <p className="shift__hint">Đang tải bảng giá…</p>
          ) : services.length === 0 ? (
            <div className="svc-empty">
              <p>Chưa có dịch vụ nào trong bảng giá.</p>
              {canManage && (
                <button className="btn btn--ghost btn--lg" onClick={() => navigate('/services')}>
                  ＋ Thêm bảng giá
                </button>
              )}
            </div>
          ) : visible.length === 0 ? (
            <p className="shift__hint">Không có dịch vụ khớp “{search}”.</p>
          ) : (
            <>
              {tierServices.map((svc) => (
                <div className="svc-tier" key={svc.id}>
                  <div className="svc-tier__name">{svc.name}</div>
                  <div className="pricing-grid">
                    {svc.tiers
                      .filter((t) => !t.per_unit)
                      .map((t) => (
                        <button key={t.id} className="tier-btn" onClick={() => addFlat(svc, t)}>
                          <span className="tier-btn__label">{t.label}</span>
                          <span className="tier-btn__price">{formatVND(t.price)}</span>
                        </button>
                      ))}
                  </div>
                  {svc.tiers
                    .filter((t) => t.per_unit)
                    .map((t) => (
                      <div className="perkg" key={t.id}>
                        <span className="perkg__label">
                          {t.label} — {formatVND(t.price)}/{UNIT_LABEL[svc.unit] || svc.unit}
                        </span>
                        <div className="perkg__row">
                          <input
                            className="input"
                            type="number"
                            inputMode="decimal"
                            min="0"
                            step="0.5"
                            placeholder={`Số ${UNIT_LABEL[svc.unit] || svc.unit}`}
                            value={overflowKg[t.id] || ''}
                            onChange={(e) =>
                              setOverflowKg((m) => ({ ...m, [t.id]: e.target.value }))
                            }
                          />
                          <button
                            className="btn btn--ghost btn--lg"
                            onClick={() => addOverflow(svc, t)}
                            disabled={toNumber(overflowKg[t.id]) <= 0}
                          >
                            ＋ Thêm
                          </button>
                        </div>
                      </div>
                    ))}
                </div>
              ))}

              {perUnitServices.length > 0 && (
                <div className="svc-grid">
                  {perUnitServices.map((svc) => (
                    <button key={svc.id} className="svc-card" onClick={() => addPerUnit(svc)}>
                      <span className="svc-card__name">{svc.name}</span>
                      <span className="svc-card__unit">{UNIT_LABEL[svc.unit] || svc.unit}</span>
                      <span className="svc-card__price">{formatVND(svc.unit_price)}</span>
                    </button>
                  ))}
                </div>
              )}
            </>
          )}

          <div className="cart">
            {cart.length === 0 ? (
              <p className="cart__empty">Bấm dịch vụ ở trên để thêm vào đơn.</p>
            ) : (
              cart.map((x) => (
                <div className="cart__item" key={x.id}>
                  <div className="cart__info">
                    <span className="cart__name">{x.name}</span>
                    <span className="cart__line">
                      {x.kind === 'flat'
                        ? `${x.count} gói × ${formatVND(x.price)}`
                        : `${x.quantity} × ${formatVND(x.unit_price)}`}{' '}
                      = <strong>{formatVND(lineTotal(x))}</strong>
                    </span>
                  </div>
                  <div className="cart__qty">
                    <button className="qty-btn" onClick={() => bump(x.id, -1)}>
                      −
                    </button>
                    <span className="qty-val">{x.kind === 'flat' ? x.count : x.quantity}</span>
                    <button className="qty-btn" onClick={() => bump(x.id, +1)}>
                      ＋
                    </button>
                    <button className="qty-btn qty-btn--del" onClick={() => removeItem(x.id)}>
                      ✕
                    </button>
                  </div>
                </div>
              ))
            )}
          </div>
        </div>

        <aside className="ordernew__side">
          <div className="card pickup-card">
            <span className="field-label">Giờ hẹn giao</span>
            <WheelTimePicker value={pickup} onChange={setPickup} />
          </div>

          <details className="customer">
            <summary>Khách hàng &amp; ghi chú (tùy chọn)</summary>
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
              <input
                className="input"
                type="text"
                placeholder="Ghi chú đơn"
                value={note}
                onChange={(e) => setNote(e.target.value)}
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
        </aside>
      </div>
    </div>
  )
}
