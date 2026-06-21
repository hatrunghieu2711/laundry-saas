import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { ApiError, api } from '../lib/api'
import { formatVND, toNumber } from '../lib/format'

// Màn quản lý QUY TẮC phụ thu / giảm giá tự áp theo ngày (owner) — Stage 5.4.
// Rule trong [start_date, end_date] được tự áp khi tạo đơn (nhân viên sửa được).
// Đổi/xóa rule CHỈ ảnh hưởng đơn MỚI — đơn cũ đã snapshot số tiền.
const EMPTY = {
  type: 'surcharge',
  value_type: 'percent',
  value: '',
  name: '',
  start_date: '',
  end_date: '',
}

function fmtRuleValue(r) {
  return r.value_type === 'percent' ? `${toNumber(r.value)}%` : formatVND(r.value)
}

export default function PriceRulesManage() {
  const { user } = useAuth()
  const canManage = user?.role === 'owner'

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [form, setForm] = useState(EMPTY)
  const [editing, setEditing] = useState(null) // rule id đang sửa (null = tạo mới)
  const [saving, setSaving] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const p = await api.get('/price-rules?limit=200')
      setItems(p.items)
    } catch (err) {
      setError(err?.message || 'Không tải được danh sách quy tắc')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const resetForm = () => {
    setForm(EMPTY)
    setEditing(null)
    setError('')
  }

  const startEdit = (r) => {
    setEditing(r.id)
    setForm({
      type: r.type,
      value_type: r.value_type,
      value: String(toNumber(r.value)),
      name: r.name,
      start_date: r.start_date,
      end_date: r.end_date,
    })
    setError('')
  }

  const save = async () => {
    if (!form.name.trim()) {
      setError('Nhập tên quy tắc (vd "Phụ thu Tết").')
      return
    }
    if (toNumber(form.value) <= 0) {
      setError('Giá trị phải lớn hơn 0.')
      return
    }
    if (!form.start_date || !form.end_date) {
      setError('Chọn ngày bắt đầu và kết thúc.')
      return
    }
    setSaving(true)
    setError('')
    const body = {
      type: form.type,
      value_type: form.value_type,
      value: toNumber(form.value),
      name: form.name.trim(),
      start_date: form.start_date,
      end_date: form.end_date,
    }
    try {
      if (editing) await api.put(`/price-rules/${editing}`, body)
      else await api.post('/price-rules', body)
      resetForm()
      await reload()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'INVALID_DATE_RANGE') {
        setError('Ngày kết thúc phải sau (hoặc bằng) ngày bắt đầu.')
      } else if (err instanceof ApiError && err.code === 'PERCENT_TOO_HIGH') {
        setError('Phần trăm không được vượt 100%.')
      } else {
        setError(err?.message || 'Không lưu được quy tắc')
      }
    } finally {
      setSaving(false)
    }
  }

  const toggleActive = async (r) => {
    try {
      await api.put(`/price-rules/${r.id}`, { is_active: !r.is_active })
      await reload()
    } catch (err) {
      setError(err?.message || 'Không đổi được trạng thái')
    }
  }

  const remove = async (r) => {
    if (!window.confirm(`Xóa hẳn quy tắc "${r.name}"? Không khôi phục được. Đơn cũ không bị ảnh hưởng.`)) return
    try {
      await api.del(`/price-rules/${r.id}`)
      await reload()
    } catch (err) {
      setError(err?.message || 'Không xóa được quy tắc')
    }
  }

  if (!canManage) {
    return <p className="shift__hint">Chỉ chủ chuỗi (owner) mới quản lý quy tắc phụ thu/giảm giá.</p>
  }

  return (
    <div className="services">
      <p className="shift__hint">
        Quy tắc trong khoảng ngày được <strong>tự áp</strong> khi tạo đơn (nhân viên sửa được).
        Đổi/xóa chỉ ảnh hưởng đơn <strong>mới</strong> — đơn cũ giữ số tiền đã chốt.
      </p>

      {/* Form tạo / sửa */}
      <div className="shift__card">
        <h3 className="card__title">{editing ? 'Sửa quy tắc' : 'Thêm quy tắc'}</h3>
        <div className="rule-form">
          <div className="seg">
            <button type="button" className={`seg__btn ${form.type === 'surcharge' ? 'seg__btn--active' : ''}`} onClick={() => set('type', 'surcharge')}>Phụ thu</button>
            <button type="button" className={`seg__btn ${form.type === 'discount' ? 'seg__btn--active' : ''}`} onClick={() => set('type', 'discount')}>Giảm giá</button>
          </div>
          <label className="field">
            <span>Tên quy tắc</span>
            <input className="input" type="text" value={form.name} placeholder="VD: Phụ thu Tết"
              onChange={(e) => set('name', e.target.value)} />
          </label>
          <div className="rule-form__row">
            <div className="seg seg--sm">
              <button type="button" className={`seg__btn ${form.value_type === 'percent' ? 'seg__btn--active' : ''}`} onClick={() => set('value_type', 'percent')}>%</button>
              <button type="button" className={`seg__btn ${form.value_type === 'fixed' ? 'seg__btn--active' : ''}`} onClick={() => set('value_type', 'fixed')}>đ</button>
            </div>
            <input className="input" type="number" min="0" inputMode="decimal"
              placeholder={form.value_type === 'percent' ? 'VD 20 (%)' : 'VD 20000 (đ)'}
              value={form.value} onChange={(e) => set('value', e.target.value)} />
          </div>
          <div className="rule-form__row">
            <label className="field">
              <span>Từ ngày</span>
              <input className="input" type="date" value={form.start_date}
                onChange={(e) => set('start_date', e.target.value)} />
            </label>
            <label className="field">
              <span>Đến ngày</span>
              <input className="input" type="date" value={form.end_date}
                onChange={(e) => set('end_date', e.target.value)} />
            </label>
          </div>

          {error && <div className="alert alert--error">{error}</div>}

          <div className="row-actions">
            {editing && (
              <button className="btn btn--ghost btn--lg" onClick={resetForm} disabled={saving}>Hủy</button>
            )}
            <button className="btn btn--primary btn--lg" onClick={save} disabled={saving}>
              {saving ? 'Đang lưu…' : editing ? 'Lưu thay đổi' : '＋ Thêm quy tắc'}
            </button>
          </div>
        </div>
      </div>

      {/* Danh sách */}
      {loading ? (
        <p className="shift__hint">Đang tải…</p>
      ) : items.length === 0 ? (
        <p className="shift__hint">Chưa có quy tắc nào.</p>
      ) : (
        <div className="cat-group">
          {items.map((r) => (
            <div className={`cat-item ${r.is_active ? '' : 'cat-item--off'}`} key={r.id}>
              <span className="cat-item__lead">
                <span className={`rule-badge ${r.type === 'surcharge' ? 'rule-badge--sur' : 'rule-badge--dis'}`}>
                  {r.type === 'surcharge' ? 'Phụ thu' : 'Giảm'}
                </span>
              </span>
              <div className="cat-item__main">
                <span className="cat-item__name">{r.name}</span>
                <span className="cat-item__meta">
                  {fmtRuleValue(r)} · {r.start_date} → {r.end_date}{!r.is_active && ' · đã ẩn'}
                </span>
              </div>
              <div className="cat-item__actions">
                <button className="btn btn--ghost btn--sm" onClick={() => toggleActive(r)}>
                  {r.is_active ? 'Ẩn' : 'Bật'}
                </button>
                <button className="btn btn--ghost btn--sm" onClick={() => startEdit(r)}>Sửa</button>
                <button className="btn btn--ghost btn--sm" onClick={() => remove(r)}>Xóa</button>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
