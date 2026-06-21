import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { formatVND } from '../lib/format'
import { UNIT_LABEL, normalizeService } from '../lib/services'

// Giá gọn: per_unit → "25.000đ/lần"; tier → "N bậc · từ …" (đồng bộ ServicesManage).
function priceLabel(svc) {
  if (svc.pricing_type === 'per_unit') {
    return `${formatVND(svc.unit_price)}/${UNIT_LABEL[svc.unit] || svc.unit}`
  }
  const first = svc.tiers?.[0]
  return first ? `${svc.tiers.length} bậc · từ ${formatVND(first.price)}` : 'theo bậc'
}

// Màn "Dịch vụ theo chi nhánh" (owner): chọn CN → toggle Hiện/Ẩn từng dịch vụ.
// Mặc định Hiện (dịch vụ KHÔNG nằm trong danh sách ẩn của CN). Ẩn = display-only:
// chỉ loại khỏi màn tạo đơn ở CN đó; giá chung, đơn cũ không đổi.
export default function BranchServiceVisibility() {
  const { user } = useAuth()
  const canManage = user?.role === 'owner'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState('')
  const [services, setServices] = useState([])
  const [hidden, setHidden] = useState(() => new Set()) // service_id đang ẩn ở CN chọn
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [savingId, setSavingId] = useState(null)

  // Tải chi nhánh + bảng dịch vụ (active) một lần.
  useEffect(() => {
    if (!canManage) {
      setLoading(false)
      return
    }
    Promise.all([api.get('/branches?limit=200'), api.get('/services?limit=200')])
      .then(([bp, sp]) => {
        const active = bp.items.filter((b) => b.status === 'active')
        setBranches(active)
        setServices(sp.items.map(normalizeService))
        if (active.length) setBranchId(active[0].id)
      })
      .catch((err) => setError(err?.message || 'Không tải được dữ liệu'))
      .finally(() => setLoading(false))
  }, [canManage])

  // Tải danh sách ẩn của CN đang chọn.
  const loadHidden = useCallback(async (bid) => {
    if (!bid) return
    setError('')
    try {
      const r = await api.get(`/branches/${bid}/hidden-services`)
      setHidden(new Set(r.hidden_service_ids))
    } catch (err) {
      setError(err?.message || 'Không tải được trạng thái ẩn/hiện')
    }
  }, [])

  useEffect(() => {
    loadHidden(branchId)
  }, [branchId, loadHidden])

  const toggle = async (svc) => {
    const isHidden = hidden.has(svc.id)
    const nextHidden = !isHidden // bấm "Ẩn" khi đang hiện → ẩn; ngược lại
    setSavingId(svc.id)
    setError('')
    try {
      await api.put(`/branches/${branchId}/hidden-services/${svc.id}`, { hidden: nextHidden })
      setHidden((prev) => {
        const n = new Set(prev)
        if (nextHidden) n.add(svc.id)
        else n.delete(svc.id)
        return n
      })
    } catch (err) {
      setError(err?.message || 'Không lưu được')
    } finally {
      setSavingId(null)
    }
  }

  // Gom dịch vụ theo DANH MỤC (category). Nhóm "Khác" (chưa phân loại) xuống cuối;
  // thứ tự nhóm theo category.display_order; trong nhóm giữ thứ tự services (đã sort BE).
  const groups = useMemo(() => {
    const map = new Map() // key → { name, order, items[] }
    for (const s of services) {
      const key = s.category_id || '__none'
      if (!map.has(key)) {
        map.set(key, {
          name: s.category?.name || 'Khác',
          order: s.category_id ? (s.category?.display_order ?? 0) : Infinity, // Khác cuối
          items: [],
        })
      }
      map.get(key).items.push(s)
    }
    return [...map.entries()]
      .map(([key, v]) => ({ key, ...v }))
      .sort((a, b) => a.order - b.order || a.name.localeCompare(b.name))
  }, [services])

  if (!canManage) {
    return <p className="shift__hint">Chỉ chủ chuỗi mới quản lý dịch vụ theo chi nhánh.</p>
  }
  if (loading) {
    return <p className="shift__hint">Đang tải…</p>
  }

  return (
    <div className="services">
      <div className="services__head">
        {branches.length > 0 && (
          <select
            className="input"
            style={{ maxWidth: 220 }}
            value={branchId}
            onChange={(e) => setBranchId(e.target.value)}
            aria-label="Chọn chi nhánh"
          >
            {branches.map((b) => (
              <option key={b.id} value={b.id}>{b.order_prefix} · {b.name}</option>
            ))}
          </select>
        )}
      </div>

      <p className="shift__hint">
        Tắt (ẩn) dịch vụ ở chi nhánh đang chọn → màn tạo đơn của CN đó KHÔNG hiện dịch vụ này.
        Giá <strong>chung</strong>; đơn cũ không đổi. Mặc định mọi dịch vụ đều hiện.
        Dấu sao = dịch vụ <strong>hay chọn</strong> (đổi ở tab “Dịch vụ &amp; bảng giá”).
      </p>

      {error && <div className="alert alert--error">{error}</div>}

      {branches.length === 0 ? (
        <p className="shift__hint">Chưa có chi nhánh nào.</p>
      ) : services.length === 0 ? (
        <p className="shift__hint">Chưa có dịch vụ nào trong bảng giá.</p>
      ) : (
        groups.map((g) => (
          <div className="cat-group" key={g.key}>
            <div className="cat-group__title">{g.name}</div>
            {g.items.map((s) => {
              const isHidden = hidden.has(s.id)
              return (
                <div className={`cat-item ${isHidden ? 'cat-item--off' : ''}`} key={s.id}>
                  {/* ★ chỉ báo "hay chọn" (KHÔNG bấm — đổi ở tab Dịch vụ); lead chừa chỗ căn lề. */}
                  <span className="cat-item__lead" aria-hidden="true">
                    {s.is_favorite && (
                      <span className="cat-item__fav cat-item__fav--ro">
                        <svg viewBox="0 0 24 24" fill="currentColor" stroke="currentColor" strokeWidth="1" strokeLinejoin="round"><path d="M12 17.75l-6.17 3.24 1.18-6.88-5-4.87 6.9-1 3.09-6.26 3.09 6.26 6.9 1-5 4.87 1.18 6.88z" /></svg>
                      </span>
                    )}
                  </span>
                  <span className="cat-item__main">
                    <span className="cat-item__name">{s.name}</span>
                    <span className="cat-item__meta">{priceLabel(s)}</span>
                  </span>
                  {isHidden && <span className="cat-item__off-tag">đang ẩn</span>}
                  <label className="switch">
                    <input
                      type="checkbox"
                      checked={!isHidden}
                      disabled={savingId === s.id}
                      onChange={() => toggle(s)}
                      aria-label={`${isHidden ? 'Hiện' : 'Ẩn'} ${s.name} ở chi nhánh này`}
                    />
                    <span className="switch__track" />
                  </label>
                </div>
              )
            })}
          </div>
        ))
      )}
    </div>
  )
}
