import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'

// Màn quản lý chi nhánh (owner): sửa TIỀN TỐ mã đơn mỗi chi nhánh.
// Tiền tố ghép số thứ tự thành order_code (vd CH1-00001). Đổi tiền tố CHỈ áp dụng
// cho đơn MỚI — đơn cũ giữ nguyên mã đã in (số thứ tự per-branch không reset).
const PREFIX_RE = /^[A-Za-z0-9]+$/

export default function BranchesManage() {
  const { user } = useAuth()
  const canManage = user?.role === 'owner'

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [editing, setEditing] = useState(null) // branch id đang sửa
  const [value, setValue] = useState('')
  const [saving, setSaving] = useState(false)

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const p = await api.get('/branches?limit=200')
      setItems(p.items)
    } catch (err) {
      setError(err?.message || 'Không tải được danh sách chi nhánh')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const startEdit = (b) => {
    setEditing(b.id)
    setValue(b.order_prefix || b.code)
    setError('')
  }

  const cancel = () => {
    setEditing(null)
    setValue('')
    setError('')
  }

  const save = async (b) => {
    const prefix = value.trim()
    if (!PREFIX_RE.test(prefix)) {
      setError('Tiền tố chỉ gồm chữ và số, không khoảng trắng/ký tự đặc biệt')
      return
    }
    setSaving(true)
    setError('')
    try {
      await api.patch(`/branches/${b.id}`, { order_prefix: prefix })
      cancel()
      await reload()
    } catch (err) {
      // PREFIX_TAKEN / INVALID_PREFIX → hiện message từ backend.
      setError(err?.message || 'Không lưu được tiền tố')
    } finally {
      setSaving(false)
    }
  }

  if (!canManage) {
    return <p className="shift__hint">Chỉ chủ chuỗi mới sửa tiền tố mã đơn.</p>
  }

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Chi nhánh &amp; mã đơn</h2>
      </div>

      <p className="shift__hint">
        Tiền tố ghép số thứ tự thành mã đơn (vd <strong>CH1-00001</strong>). Đổi tiền tố CHỈ
        áp dụng cho đơn <strong>mới</strong> — đơn cũ giữ nguyên mã đã in.
      </p>

      {error && <div className="alert alert--error">{error}</div>}

      {loading ? (
        <p className="shift__hint">Đang tải…</p>
      ) : items.length === 0 ? (
        <p className="shift__hint">Chưa có chi nhánh nào.</p>
      ) : (
        <div className="cat-manage-list">
          {items.map((b) => {
            const preview = (editing === b.id ? value.trim() : b.order_prefix) || '?'
            return (
              <div className="cat-manage" key={b.id}>
                <div className="cat-manage__name" style={{ flex: 1 }}>
                  <strong>{b.name}</strong>
                  <div className="shift__hint" style={{ margin: '2px 0 0' }}>
                    Mã đơn tiếp theo: {preview}-00001
                  </div>
                </div>

                {editing === b.id ? (
                  <>
                    <input
                      className="input"
                      style={{ maxWidth: 130 }}
                      value={value}
                      autoFocus
                      maxLength={16}
                      placeholder="vd CH1"
                      onChange={(e) => setValue(e.target.value)}
                    />
                    <div className="cat-manage__actions">
                      <button
                        className="btn btn--ghost btn--sm"
                        onClick={cancel}
                        disabled={saving}
                      >
                        Hủy
                      </button>
                      <button
                        className="btn btn--primary btn--sm"
                        onClick={() => save(b)}
                        disabled={saving}
                      >
                        {saving ? '…' : 'Lưu'}
                      </button>
                    </div>
                  </>
                ) : (
                  <>
                    <span className="cat-manage__icon">{b.order_prefix}</span>
                    <div className="cat-manage__actions">
                      <button
                        className="btn btn--ghost btn--sm"
                        onClick={() => startEdit(b)}
                      >
                        Sửa tiền tố
                      </button>
                    </div>
                  </>
                )}
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
