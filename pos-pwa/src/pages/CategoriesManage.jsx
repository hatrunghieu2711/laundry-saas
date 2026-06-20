import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { CATEGORY_ICONS, DEFAULT_CATEGORY_ICON, normalizeCategory } from '../lib/categories'

// Màn quản lý danh mục dịch vụ (owner/manager): thêm/sửa/xóa(soft) + sắp thứ tự ↑/↓.
function blankForm() {
  return { id: null, name: '', icon: DEFAULT_CATEGORY_ICON }
}

export default function CategoriesManage() {
  const { user } = useAuth()
  const canManage = user?.role === 'owner' || user?.role === 'manager'

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [form, setForm] = useState(null)
  const [saving, setSaving] = useState(false)
  const [confirmDel, setConfirmDel] = useState(null)

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const p = await api.get('/categories?limit=200')
      setItems(p.items.map(normalizeCategory))
    } catch (err) {
      setError(err?.message || 'Không tải được danh mục')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const save = async () => {
    const name = form.name.trim()
    if (!name) {
      setError('Nhập tên danh mục')
      return
    }
    setSaving(true)
    setError('')
    try {
      const body = { name, icon: form.icon || null }
      if (form.id) await api.put(`/categories/${form.id}`, body)
      else await api.post('/categories', { ...body, display_order: items.length })
      setForm(null)
      await reload()
    } catch (err) {
      setError(err?.message || 'Không lưu được danh mục')
    } finally {
      setSaving(false)
    }
  }

  const doDelete = async (cat) => {
    setSaving(true)
    setError('')
    try {
      await api.del(`/categories/${cat.id}`)
      setConfirmDel(null)
      await reload()
    } catch (err) {
      // CATEGORY_IN_USE → báo còn N dịch vụ.
      setError(err?.message || 'Không xóa được danh mục')
      setConfirmDel(null)
    } finally {
      setSaving(false)
    }
  }

  // Đổi chỗ trong danh sách rồi gọi reorder.
  const move = async (idx, dir) => {
    const j = idx + dir
    if (j < 0 || j >= items.length) return
    const next = [...items]
    ;[next[idx], next[j]] = [next[j], next[idx]]
    setItems(next) // optimistic
    try {
      await api.put('/categories/reorder', { ids: next.map((c) => c.id) })
    } catch (err) {
      setError(err?.message || 'Không sắp được thứ tự')
      await reload()
    }
  }

  if (!canManage) {
    return <p className="shift__hint">Chỉ chủ chuỗi / quản lý mới quản lý danh mục.</p>
  }

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Danh mục dịch vụ</h2>
        {!form && (
          <button className="btn btn--primary btn--lg" onClick={() => setForm(blankForm())}>
            ＋ Thêm danh mục
          </button>
        )}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {form && (
        <div className="shift__card svc-form">
          <h3 className="card__title">{form.id ? 'Sửa danh mục' : 'Danh mục mới'}</h3>

          <label className="field">
            <span>Tên danh mục</span>
            <input
              className="input"
              type="text"
              placeholder="vd Giặt sấy, Đồ lẻ, Chăn ga"
              value={form.name}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
              autoFocus
            />
          </label>

          <div className="field">
            <span>Biểu tượng</span>
            <div className="icon-picker">
              {CATEGORY_ICONS.map((ic) => (
                <button
                  type="button"
                  key={ic}
                  className={`icon-opt ${form.icon === ic ? 'icon-opt--active' : ''}`}
                  onClick={() => setForm((f) => ({ ...f, icon: ic }))}
                >
                  {ic}
                </button>
              ))}
            </div>
          </div>

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

      {loading ? (
        <p className="shift__hint">Đang tải…</p>
      ) : items.length === 0 ? (
        <p className="shift__hint">Chưa có danh mục nào. Thêm danh mục để gom dịch vụ.</p>
      ) : (
        <div className="cat-manage-list">
          {items.map((cat, idx) => (
            <div className="cat-manage" key={cat.id}>
              <div className="cat-manage__order">
                <button
                  className="qty-btn"
                  onClick={() => move(idx, -1)}
                  disabled={idx === 0}
                  aria-label="Lên"
                >
                  ↑
                </button>
                <button
                  className="qty-btn"
                  onClick={() => move(idx, +1)}
                  disabled={idx === items.length - 1}
                  aria-label="Xuống"
                >
                  ↓
                </button>
              </div>
              <span className="cat-manage__icon">{cat.icon || DEFAULT_CATEGORY_ICON}</span>
              <span className="cat-manage__name">{cat.name}</span>
              <div className="cat-manage__actions">
                <button className="btn btn--ghost btn--sm" onClick={() => setForm({ ...cat })}>
                  Sửa
                </button>
                {confirmDel === cat.id ? (
                  <button
                    className="btn btn--danger btn--sm"
                    onClick={() => doDelete(cat)}
                    disabled={saving}
                  >
                    Xóa?
                  </button>
                ) : (
                  <button className="btn btn--ghost btn--sm" onClick={() => setConfirmDel(cat.id)}>
                    Xóa
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
