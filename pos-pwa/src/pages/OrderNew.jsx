import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import Receipt from '../components/Receipt'
import WheelTimePicker from '../components/WheelTimePicker'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'
import { defaultPickupVnWall, isPastVnWall, vnWallToISO } from '../lib/datetime'
import { UNIT_LABEL, normalizeService } from '../lib/services'

// Màn tạo đơn (Stage 3.8): layout 3 vùng KHÔNG cuộn toàn trang
// (tab danh mục | lưới dịch vụ | giỏ). Bấm TẠO ĐƠN → modal xác nhận
// (SĐT/tên khách + wheel giờ giao) rồi mới tạo.
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
  const [activeTab, setActiveTab] = useState('__fav')
  const [cart, setCart] = useState([])
  const [overflowKg, setOverflowKg] = useState({})
  const [turnaround, setTurnaround] = useState(4) // từ tenant settings
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState(null)
  const idRef = useRef(0)

  // ── modal xác nhận ──
  const [showConfirm, setShowConfirm] = useState(false)
  const [phone, setPhone] = useState('')
  const [custName, setCustName] = useState('')
  const [custFound, setCustFound] = useState(null)
  const [note, setNote] = useState('')
  const [pickup, setPickup] = useState(() => defaultPickupVnWall(4))

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

  useEffect(() => {
    setSvcLoading(true)
    api
      .get('/services?limit=200')
      .then((p) => setServices(p.items.map(normalizeService)))
      .catch(() => setServices([]))
      .finally(() => setSvcLoading(false))
  }, [])

  // Turnaround chuẩn của tenant (gợi ý giờ giao). Lỗi → giữ mặc định 4.
  useEffect(() => {
    api
      .get('/settings/pos')
      .then((s) => setTurnaround(s.default_turnaround_hours ?? 4))
      .catch(() => {})
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
      setShiftState('none')
      if (!(err instanceof ApiError && err.status === 404)) setError(err?.message || '')
    }
  }, [isOwner, branchId])

  useEffect(() => {
    checkShift()
  }, [checkShift])

  // ── giỏ ──
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
        { id: newId(), kind: 'per_unit', service_id: svc.id, name: svc.name,
          unit: svc.unit, unit_price: svc.unit_price, quantity: 1 },
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
        { id: newId(), kind: 'flat', service_id: svc.id, tier_id: tier.id,
          name: `${svc.name} (${tier.label})`, price: tier.price,
          weight: tier.max_value ?? 0, count: 1 },
      ]
    })
  }
  const addOverflow = (svc, tier) => {
    const kg = toNumber(overflowKg[tier.id])
    if (kg <= 0) return
    setCart((prev) => [
      ...prev,
      { id: newId(), kind: 'overflow', service_id: svc.id,
        name: `${svc.name} (${tier.label})`, unit_price: tier.price, quantity: kg },
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

  // ── danh mục (tab) ──
  const tabs = useMemo(() => {
    const favs = services.filter((s) => s.is_favorite)
    const cats = []
    const seen = new Set()
    for (const s of services) {
      if (s.category && !seen.has(s.category)) {
        seen.add(s.category)
        cats.push(s.category)
      }
    }
    const uncat = services.filter((s) => !s.category)
    const list = [{ key: '__fav', label: 'Hay chọn', icon: '⭐', items: favs }]
    for (const c of cats) {
      list.push({ key: c, label: c, icon: '🧺', items: services.filter((s) => s.category === c) })
    }
    if (uncat.length) list.push({ key: '__other', label: 'Khác', icon: '📦', items: uncat })
    return list
  }, [services])

  // Chọn tab đầu tiên có dịch vụ khi danh sách đổi.
  useEffect(() => {
    if (!tabs.length) return
    const cur = tabs.find((t) => t.key === activeTab)
    if (!cur || cur.items.length === 0) {
      const firstWithItems = tabs.find((t) => t.items.length) || tabs[0]
      setActiveTab(firstWithItems.key)
    }
  }, [tabs, activeTab])

  const q = search.trim().toLowerCase()
  const currentTab = tabs.find((t) => t.key === activeTab) || tabs[0]
  const shown = q
    ? services.filter((s) => s.name.toLowerCase().includes(q))
    : currentTab?.items || []
  const tierServices = shown.filter((s) => s.pricing_type === 'tier')
  const perUnitServices = shown.filter((s) => s.pricing_type === 'per_unit')

  // ── modal ──
  const openConfirm = () => {
    if (cart.length === 0) return
    setPickup(defaultPickupVnWall(turnaround))
    setError('')
    setShowConfirm(true)
  }

  // Tra khách theo SĐT (debounce) khi modal mở.
  useEffect(() => {
    if (!showConfirm) return undefined
    const ph = phone.trim()
    if (ph.length < 3) {
      setCustFound(null)
      return undefined
    }
    let alive = true
    const t = setTimeout(async () => {
      try {
        const found = await api.get(`/customers?phone=${encodeURIComponent(ph)}&limit=1`)
        if (!alive) return
        if (found.total > 0) {
          setCustFound(found.items[0])
          setCustName(found.items[0].full_name || '')
        } else {
          setCustFound(null)
        }
      } catch {
        if (alive) setCustFound(null)
      }
    }, 400)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [phone, showConfirm])

  const submit = async () => {
    if (cart.length === 0) return
    if (isPastVnWall(pickup)) {
      setError('Không thể hẹn giờ giao trong quá khứ. Chọn lại giờ giao.')
      return
    }
    setBusy(true)
    setError('')
    try {
      let customerId
      const ph = phone.trim()
      if (ph) {
        if (custFound) customerId = custFound.id
        else {
          const c = await api.post('/customers', { phone: ph, full_name: custName.trim() || undefined })
          customerId = c.id
        }
      }
      const body = { items: buildItems(), pickup_at: vnWallToISO(pickup) }
      if (customerId) body.customer_id = customerId
      if (note.trim()) body.notes = note.trim()
      if (isOwner) body.branch_id = branchId
      const order = await api.post('/orders', body)
      setShowConfirm(false)
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
    setCustFound(null)
    setNote('')
    setOverflowKg({})
    setSearch('')
    setError('')
  }

  // ── màn kết quả ──
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
        <Receipt order={created} paid={0} />
      </div>
    )
  }

  if (shiftState === 'loading') return <p className="shift__hint">Đang kiểm tra ca…</p>

  const branchPicker = isOwner && (
    <div className="branch-picker">
      <div className="branch-picker__chips">
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

  // ── builder 3 vùng ──
  const serviceArea = svcLoading ? (
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
  ) : shown.length === 0 ? (
    <p className="shift__hint">{q ? `Không có dịch vụ khớp “${search}”.` : 'Danh mục trống.'}</p>
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
                    onChange={(e) => setOverflowKg((m) => ({ ...m, [t.id]: e.target.value }))}
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
  )

  return (
    <div className="ordernew ordernew--zones">
      {branchPicker}
      {error && !showConfirm && <div className="alert alert--error">{error}</div>}

      <div className="zones">
        {/* Vùng trái: tab danh mục */}
        <nav className="zones__tabs">
          {tabs.map((t) => (
            <button
              key={t.key}
              className={`cat-tab ${activeTab === t.key ? 'cat-tab--active' : ''}`}
              onClick={() => {
                setSearch('')
                setActiveTab(t.key)
              }}
            >
              <span className="cat-tab__icon">{t.icon}</span>
              <span className="cat-tab__label">{t.label}</span>
            </button>
          ))}
        </nav>

        {/* Vùng giữa: lưới dịch vụ + ô tìm ở dưới */}
        <div className="zones__mid">
          <div className="zones__grid">{serviceArea}</div>
          <input
            className="input zones__search"
            type="search"
            placeholder="🔍 Tìm dịch vụ…"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>

        {/* Vùng phải: giỏ + nút tạo đơn */}
        <aside className="zones__cart">
          <div className="zones__cart-list">
            {cart.length === 0 ? (
              <p className="cart__empty">Bấm dịch vụ để thêm vào đơn.</p>
            ) : (
              cart.map((x) => (
                <div className="cart__item" key={x.id}>
                  <div className="cart__top">
                    <span className="cart__name" title={x.name}>{x.name}</span>
                    <button className="cart__del" onClick={() => removeItem(x.id)} aria-label="Xóa">
                      ✕
                    </button>
                  </div>
                  <div className="cart__bot">
                    <div className="cart__qty">
                      <button className="qty-btn" onClick={() => bump(x.id, -1)}>
                        −
                      </button>
                      <span className="qty-val">{x.kind === 'flat' ? x.count : x.quantity}</span>
                      <button className="qty-btn" onClick={() => bump(x.id, +1)}>
                        ＋
                      </button>
                    </div>
                    <span className="cart__amt">{formatVND(lineTotal(x))}</span>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="zones__cart-foot">
            <div className="order-bar__total">
              <span>Tổng</span>
              <strong>{formatVND(total)}</strong>
            </div>
            <button
              className="btn btn--primary btn--xl btn--block"
              onClick={openConfirm}
              disabled={cart.length === 0}
            >
              TẠO ĐƠN
            </button>
          </div>
        </aside>
      </div>

      {/* Modal xác nhận: khách + giờ giao */}
      {showConfirm && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal modal--confirm">
            <h3 className="modal__title">Xác nhận đơn</h3>

            <div className="modal__cols">
              {/* Trái: thông tin khách */}
              <div className="modal__col">
                <label className="field">
                  <span>SĐT khách (trống = khách vãng lai)</span>
                  <input
                    className="input"
                    type="tel"
                    inputMode="numeric"
                    placeholder="VD 0905..."
                    value={phone}
                    onChange={(e) => setPhone(e.target.value)}
                  />
                </label>
                {phone.trim() && (
                  <p className={`cust-hint ${custFound ? 'cust-hint--known' : ''}`}>
                    {custFound
                      ? `✓ Khách quen: ${custFound.full_name || '(chưa có tên)'}`
                      : 'Khách mới — nhập tên'}
                  </p>
                )}
                <label className="field">
                  <span>Tên khách</span>
                  <input
                    className="input"
                    type="text"
                    placeholder="Tên khách (tùy chọn)"
                    value={custName}
                    onChange={(e) => setCustName(e.target.value)}
                  />
                </label>
                <label className="field">
                  <span>Ghi chú</span>
                  <input
                    className="input"
                    type="text"
                    placeholder="VD: giặt riêng…"
                    value={note}
                    onChange={(e) => setNote(e.target.value)}
                  />
                </label>
              </div>

              {/* Phải: giờ giao */}
              <div className="modal__col">
                <span className="field-label">Giờ hẹn giao</span>
                <WheelTimePicker value={pickup} onChange={setPickup} />
              </div>
            </div>

            {error && <div className="alert alert--error">{error}</div>}

            <div className="modal__actions modal__actions--row">
              <button
                className="btn btn--ghost btn--lg"
                onClick={() => {
                  setShowConfirm(false)
                  setError('')
                }}
                disabled={busy}
              >
                Quay lại
              </button>
              <button
                className="btn btn--primary btn--xl"
                onClick={submit}
                disabled={busy || isPastVnWall(pickup)}
              >
                {busy ? 'Đang tạo…' : `Tạo đơn · ${formatVND(total)}`}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
