import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'
import { normalizeCategory } from '../lib/categories'

// Màn quản lý danh mục dịch vụ (owner/manager): thêm/sửa/xóa(soft) + sắp thứ tự ↑/↓.
// Bỏ icon emoji (CHUẨN STYLE không emoji) — danh mục hiển thị bằng TÊN.
function blankForm() {
  return { id: null, name: '' }
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
      const body = { name }
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
        <div className="cat-group">
          {items.map((cat, idx) => (
            <div className="cat-item" key={cat.id}>
              <span className="cat-item__lead">
                <span className="cat-item__order">
                  <button className="btn btn--ghost btn--sm" onClick={() => move(idx, -1)}
                    disabled={idx === 0} aria-label="Lên">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M18 15l-6-6-6 6" /></svg>
                  </button>
                  <button className="btn btn--ghost btn--sm" onClick={() => move(idx, +1)}
                    disabled={idx === items.length - 1} aria-label="Xuống">
                    <svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M6 9l6 6 6-6" /></svg>
                  </button>
                </span>
              </span>
              <div className="cat-item__main">
                <span className="cat-item__name">{cat.name}</span>
              </div>
              <div className="cat-item__actions">
                <button className="btn btn--ghost btn--sm" onClick={() => setForm({ ...cat })}>Sửa</button>
                {confirmDel === cat.id ? (
                  <button className="btn btn--danger btn--sm" onClick={() => doDelete(cat)} disabled={saving}>Xóa?</button>
                ) : (
                  <button className="btn btn--ghost btn--sm" onClick={() => setConfirmDel(cat.id)}>Xóa</button>
                )}
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  )
}
