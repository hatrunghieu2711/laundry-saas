import { useEffect, useMemo, useRef, useState } from 'react'
import { formatVND, toNumber } from '../lib/format'
import { UNIT_LABEL } from '../lib/services'

// Bộ chọn dịch vụ (tab danh mục + lưới + ô tìm). Tách khỏi OrderNew (M1, pure refactor) để dùng lại
// ở màn sửa hạng mục (M2). State nội bộ: activeTab / search / overflowKg. KHÔNG fetch, KHÔNG chạm giỏ
// — mọi thao tác thêm món phát ra onPick(payload); nơi dùng tự dựng item (giỏ OrderNew / API M2).
// resetSignal: nơi dùng bump (số tăng dần) sau khi tạo đơn → xóa search + overflowKg, GIỮ NGUYÊN
// activeTab (đúng như startNew cũ: chỉ setOverflowKg({}) + setSearch(''), KHÔNG reset tab).
export default function ServicePicker({
  services,
  loading,
  canManage,
  onManagePrices,
  onPick,
  resetSignal,
}) {
  const [search, setSearch] = useState('')
  const [activeTab, setActiveTab] = useState('__fav')
  const [overflowKg, setOverflowKg] = useState({})

  // ── danh mục (tab) — mỗi category theo display_order ──
  const tabs = useMemo(() => {
    const favs = services.filter((s) => s.is_favorite)
    const catMap = new Map()
    for (const s of services) {
      if (s.category_id && s.category && !catMap.has(s.category_id)) {
        catMap.set(s.category_id, s.category)
      }
    }
    const cats = [...catMap.values()].sort(
      (a, b) =>
        (a.display_order ?? 0) - (b.display_order ?? 0) || a.name.localeCompare(b.name),
    )
    const uncat = services.filter((s) => !s.category_id)
    const list = [{ key: '__fav', label: 'Hay chọn', items: favs }]
    for (const c of cats) {
      list.push({
        key: c.id,
        label: c.name,
        items: services.filter((s) => s.category_id === c.id),
      })
    }
    if (uncat.length) list.push({ key: '__other', label: 'Khác', items: uncat })
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

  // Reset sau khi tạo đơn: xóa search + overflowKg, GIỮ activeTab. Bỏ qua lần mount đầu
  // (resetSignal khởi tạo = 0) để không clobber vô ích.
  const didMount = useRef(false)
  useEffect(() => {
    if (!didMount.current) {
      didMount.current = true
      return
    }
    setSearch('')
    setOverflowKg({})
  }, [resetSignal])

  const q = search.trim().toLowerCase()
  const currentTab = tabs.find((t) => t.key === activeTab) || tabs[0]
  const shown = q
    ? services.filter((s) => s.name.toLowerCase().includes(q))
    : currentTab?.items || []
  const tierServices = shown.filter((s) => s.pricing_type === 'tier')
  const perUnitServices = shown.filter((s) => s.pricing_type === 'per_unit')

  const pickPerUnit = (svc) =>
    onPick({ kind: 'per_unit', service: svc, service_id: svc.id, quantity: 1, label: svc.name })

  const pickFlat = (svc, tier) =>
    onPick({
      kind: 'flat',
      service: svc,
      tier,
      service_id: svc.id,
      quantity: tier.max_value ?? 0,
      label: `${svc.name} (${tier.label})`,
    })

  const pickOverflow = (svc, tier) => {
    const kg = toNumber(overflowKg[tier.id])
    if (kg <= 0) return
    onPick({
      kind: 'overflow',
      service: svc,
      tier,
      service_id: svc.id,
      quantity: kg,
      label: `${svc.name} (${tier.label})`,
    })
    setOverflowKg((m) => ({ ...m, [tier.id]: '' }))
  }

  const serviceArea = loading ? (
    <p className="shift__hint">Đang tải bảng giá…</p>
  ) : services.length === 0 ? (
    <div className="svc-empty">
      <p>Chưa có dịch vụ nào trong bảng giá.</p>
      {canManage && (
        <button className="btn btn--ghost btn--lg" onClick={onManagePrices}>
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
                <button key={t.id} className="tier-btn" onClick={() => pickFlat(svc, t)}>
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
                    onClick={() => pickOverflow(svc, t)}
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
            <button key={svc.id} className="svc-card" onClick={() => pickPerUnit(svc)}>
              <span className="svc-card__name">{svc.name}</span>
              <span className="svc-card__meta">
                <span className="svc-card__unit">{UNIT_LABEL[svc.unit] || svc.unit}</span>
                <span className="svc-card__price">{formatVND(svc.unit_price)}</span>
              </span>
            </button>
          ))}
        </div>
      )}
    </>
  )

  return (
    <>
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
            {/* Monogram chữ cái đầu — ổn định trên Chrome cũ Sunmi (emoji hiện □). */}
            <span className="cat-tab__icon" aria-hidden="true">
              {(t.label || '?').trim().charAt(0).toUpperCase()}
            </span>
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
          placeholder="Tìm dịch vụ…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
      </div>
    </>
  )
}
