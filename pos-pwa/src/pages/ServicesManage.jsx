import { useCallback, useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { normalizeCategory } from '../lib/categories'
import { formatVND } from '../lib/format'
import { UNITS, UNIT_LABEL, normalizeService } from '../lib/services'

// Màn quản lý bảng giá (owner/manager): thêm/sửa/xóa(soft) dịch vụ + bậc giá.
// Đây là nơi owner tự thêm "Áo Vest", "Ủi đồ"… không cần lập trình viên.
const EMPTY_TIER = { label: '', max_value: '', price: '', per_unit: false }

function blankForm() {
  return {
    id: null, name: '', unit: 'kg', pricing_type: 'per_unit', unit_price: '',
    category_id: '', is_favorite: false, tiers: [{ ...EMPTY_TIER }],
  }
}

function toForm(svc) {
  return {
    id: svc.id,
    name: svc.name,
    unit: svc.unit,
    pricing_type: svc.pricing_type,
    category_id: svc.category_id || '',
    is_favorite: !!svc.is_favorite,
    unit_price: svc.pricing_type === 'per_unit' ? String(svc.unit_price) : '',
    tiers:
      svc.pricing_type === 'tier' && svc.tiers.length
        ? svc.tiers.map((t) => ({
            label: t.label,
            max_value: t.max_value == null ? '' : String(t.max_value),
            price: String(t.price),
            per_unit: !!t.per_unit,
          }))
        : [{ ...EMPTY_TIER }],
  }
}

export default function ServicesManage() {
  const { user } = useAuth()
  const canManage = user?.role === 'owner' || user?.role === 'manager'

  const [items, setItems] = useState([])
  const [categories, setCategories] = useState([])
  const [showInactive, setShowInactive] = useState(false)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [form, setForm] = useState(null) // null = đóng form; object = đang thêm/sửa
  const [saving, setSaving] = useState(false)
  const [confirmDel, setConfirmDel] = useState(null)

  // Danh mục cho dropdown (chọn từ danh sách chuẩn, không gõ text tự do).
  useEffect(() => {
    api
      .get('/categories?limit=200')
      .then((p) => setCategories(p.items.map(normalizeCategory)))
      .catch(() => setCategories([]))
  }, [])

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const q = showInactive ? '?include_inactive=true&limit=200' : '?limit=200'
      const p = await api.get(`/services${q}`)
      setItems(p.items.map(normalizeService))
    } catch (err) {
      setError(err?.message || 'Không tải được bảng giá')
    } finally {
      setLoading(false)
    }
  }, [showInactive])

  useEffect(() => {
    reload()
  }, [reload])

  const setField = (k, v) => setForm((f) => ({ ...f, [k]: v }))
  const setTier = (i, k, v) =>
    setForm((f) => ({ ...f, tiers: f.tiers.map((t, j) => (j === i ? { ...t, [k]: v } : t)) }))
  const addTier = () => setForm((f) => ({ ...f, tiers: [...f.tiers, { ...EMPTY_TIER }] }))
  const removeTier = (i) => setForm((f) => ({ ...f, tiers: f.tiers.filter((_, j) => j !== i) }))

  const save = async () => {
    const name = form.name.trim()
    if (!name) {
      setError('Nhập tên dịch vụ')
      return
    }
    const payload = {
      name,
      unit: form.unit,
      pricing_type: form.pricing_type,
      display_order: 0,
      category_id: form.category_id || null,
      is_favorite: !!form.is_favorite,
    }
    if (form.pricing_type === 'per_unit') {
      payload.unit_price = Number(form.unit_price) || 0
    } else {
      const tiers = form.tiers
        .filter((t) => t.label.trim() && t.price !== '')
        .map((t, i) => ({
          label: t.label.trim(),
          max_value: t.max_value === '' ? null : Number(t.max_value),
          price: Number(t.price) || 0,
          per_unit: !!t.per_unit,
          display_order: i,
        }))
      if (tiers.length === 0) {
        setError('Dịch vụ theo bậc cần ít nhất 1 bậc giá (tên + giá)')
        return
      }
      payload.tiers = tiers
    }
    setSaving(true)
    setError('')
    try {
      if (form.id) await api.put(`/services/${form.id}`, payload)
      else await api.post('/services', payload)
      setForm(null)
      await reload()
    } catch (err) {
      setError(err?.message || 'Không lưu được dịch vụ')
    } finally {
      setSaving(false)
    }
  }

  const doDelete = async (svc) => {
    setSaving(true)
    setError('')
    try {
      await api.del(`/services/${svc.id}`)
      setConfirmDel(null)
      await reload()
    } catch (err) {
      setError(err?.message || 'Không xóa được dịch vụ')
    } finally {
      setSaving(false)
    }
  }

  const reactivate = async (svc) => {
    try {
      await api.put(`/services/${svc.id}`, { is_active: true })
      await reload()
    } catch (err) {
      setError(err?.message || '')
    }
  }

  const toggleFavorite = async (svc) => {
    try {
      await api.put(`/services/${svc.id}`, { is_favorite: !svc.is_favorite })
      await reload()
    } catch (err) {
      setError(err?.message || 'Không đổi được "Hay chọn"')
    }
  }

  const priceLabel = (svc) => {
    if (svc.pricing_type === 'per_unit') return `${formatVND(svc.unit_price)}/${UNIT_LABEL[svc.unit] || svc.unit}`
    const n = svc.tiers.length
    const first = svc.tiers[0]
    return first ? `${n} bậc · từ ${formatVND(first.price)}` : 'theo bậc'
  }

  if (!canManage) {
    return <p className="shift__hint">Chỉ chủ chuỗi / quản lý mới quản lý bảng giá.</p>
  }

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Bảng giá dịch vụ</h2>
        {!form && (
          <button className="btn btn--primary btn--lg" onClick={() => setForm(blankForm())}>
            ＋ Thêm dịch vụ
          </button>
        )}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {form && (
        <div className="card svc-form">
          <h3 className="card__title">{form.id ? 'Sửa dịch vụ' : 'Dịch vụ mới'}</h3>

          <label className="field">
            <span>Tên dịch vụ</span>
            <input
              className="input"
              type="text"
              placeholder="vd Áo Vest, Ủi đồ, Giặt sấy"
              value={form.name}
              onChange={(e) => setField('name', e.target.value)}
            />
          </label>

          <label className="field">
            <span>Danh mục (gom tab màn tạo đơn)</span>
            <select
              className="input"
              value={form.category_id}
              onChange={(e) => setField('category_id', e.target.value)}
            >
              <option value="">— Chưa phân loại (nhóm “Khác”) —</option>
              {categories.map((c) => (
                <option key={c.id} value={c.id}>
                  {(c.icon ? `${c.icon} ` : '') + c.name}
                </option>
              ))}
            </select>
            <Link className="svc-form__link" to="/categories">
              ⚙ Quản lý danh mục
            </Link>
          </label>

          <label className="svc-fav-toggle">
            <input
              type="checkbox"
              checked={form.is_favorite}
              onChange={(e) => setField('is_favorite', e.target.checked)}
            />
            ⭐ Hay chọn (hiện ở tab đầu khi tạo đơn)
          </label>

          <label className="field">
            <span>Đơn vị tính</span>
            <select className="input" value={form.unit} onChange={(e) => setField('unit', e.target.value)}>
              {UNITS.map((u) => (
                <option key={u.value} value={u.value}>
                  {u.label}
                </option>
              ))}
            </select>
          </label>

          <div className="field">
            <span>Loại tính tiền</span>
            <div className="seg">
              <button
                className={`seg__btn ${form.pricing_type === 'per_unit' ? 'seg__btn--active' : ''}`}
                onClick={() => setField('pricing_type', 'per_unit')}
              >
                Theo đơn vị (× số lượng)
              </button>
              <button
                className={`seg__btn ${form.pricing_type === 'tier' ? 'seg__btn--active' : ''}`}
                onClick={() => setField('pricing_type', 'tier')}
              >
                Theo bậc cân (trọn gói)
              </button>
            </div>
          </div>

          {form.pricing_type === 'per_unit' ? (
            <label className="field">
              <span>Đơn giá (đ/{UNIT_LABEL[form.unit] || form.unit})</span>
              <input
                className="input"
                type="number"
                inputMode="numeric"
                min="0"
                placeholder="vd 60000"
                value={form.unit_price}
                onChange={(e) => setField('unit_price', e.target.value)}
              />
            </label>
          ) : (
            <div className="field">
              <span>Các bậc giá</span>
              <p className="svc-form__hint">
                Bậc trọn gói: nhập “đến mức” (vd 3) + giá. Bậc vượt ngưỡng (tính theo đơn
                vị): để trống “đến mức” và tích “× đơn vị”.
              </p>
              <div className="tier-edit__head">
                <span>Nhãn</span>
                <span>Đến mức</span>
                <span>Giá</span>
                <span>× ĐV</span>
                <span />
              </div>
              {form.tiers.map((t, i) => (
                <div className="tier-edit" key={i}>
                  <input
                    className="input"
                    type="text"
                    placeholder="≤3kg"
                    value={t.label}
                    onChange={(e) => setTier(i, 'label', e.target.value)}
                  />
                  <input
                    className="input"
                    type="number"
                    inputMode="decimal"
                    min="0"
                    step="0.5"
                    placeholder="3"
                    value={t.max_value}
                    onChange={(e) => setTier(i, 'max_value', e.target.value)}
                  />
                  <input
                    className="input"
                    type="number"
                    inputMode="numeric"
                    min="0"
                    placeholder="60000"
                    value={t.price}
                    onChange={(e) => setTier(i, 'price', e.target.value)}
                  />
                  <label className="tier-edit__chk">
                    <input
                      type="checkbox"
                      checked={t.per_unit}
                      onChange={(e) => setTier(i, 'per_unit', e.target.checked)}
                    />
                  </label>
                  <button
                    className="qty-btn qty-btn--del"
                    onClick={() => removeTier(i)}
                    disabled={form.tiers.length <= 1}
                  >
                    ✕
                  </button>
                </div>
              ))}
              <button className="btn btn--ghost btn--sm" onClick={addTier}>
                ＋ Thêm bậc
              </button>
            </div>
          )}

          <div className="row-actions">
            <button className="btn btn--ghost btn--lg" onClick={() => setForm(null)} disabled={saving}>
              Hủy
            </button>
            <button className="btn btn--primary btn--lg" onClick={save} disabled={saving}>
              {saving ? 'Đang lưu…' : 'Lưu'}
            </button>
          </div>
        </div>
      )}

      <label className="services__toggle">
        <input
          type="checkbox"
          checked={showInactive}
          onChange={(e) => setShowInactive(e.target.checked)}
        />
        Hiện cả dịch vụ đã ẩn
      </label>

      {loading ? (
        <p className="shift__hint">Đang tải…</p>
      ) : items.length === 0 ? (
        <p className="shift__hint">Chưa có dịch vụ nào.</p>
      ) : (
        <div className="svc-manage-list">
          {items.map((svc) => (
            <div className={`svc-manage ${svc.is_active ? '' : 'svc-manage--off'}`} key={svc.id}>
              <div className="svc-manage__info">
                <span className="svc-manage__name">
                  {svc.is_favorite && <span className="svc-manage__star" title="Hay chọn">⭐</span>}
                  {svc.name}
                  {svc.category && (
                    <span className="svc-manage__cat">
                      {(svc.category.icon ? `${svc.category.icon} ` : '') + svc.category.name}
                    </span>
                  )}
                  {!svc.is_active && <span className="svc-manage__badge">đã ẩn</span>}
                </span>
                <span className="svc-manage__meta">
                  {svc.pricing_type === 'tier' ? 'Theo bậc' : 'Theo đơn vị'} · {priceLabel(svc)}
                </span>
              </div>
              <div className="svc-manage__actions">
                {svc.is_active ? (
                  <>
                    <button
                      className={`btn btn--ghost btn--sm ${svc.is_favorite ? 'btn--fav-on' : ''}`}
                      onClick={() => toggleFavorite(svc)}
                      title='Bật/tắt "Hay chọn"'
                    >
                      {svc.is_favorite ? '★' : '☆'}
                    </button>
                    <button className="btn btn--ghost btn--sm" onClick={() => setForm(toForm(svc))}>
                      Sửa
                    </button>
                    {confirmDel === svc.id ? (
                      <button className="btn btn--danger btn--sm" onClick={() => doDelete(svc)} disabled={saving}>
                        Xóa?
                      </button>
                    ) : (
                      <button className="btn btn--ghost btn--sm" onClick={() => setConfirmDel(svc.id)}>
                        Xóa
                      </button>
                    )}
                  </>
                ) : (
                  <button className="btn btn--ghost btn--sm" onClick={() => reactivate(svc)}>
                    Khôi phục
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
