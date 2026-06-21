import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { ApiError, api } from '../lib/api'

// Màn quản lý chi nhánh (owner): thêm / sửa (tên, địa chỉ, SĐT, tiền tố) / xóa (mềm).
// Tiền tố (order_prefix) ghép số thứ tự thành mã đơn (vd CH1-00001). Đổi tiền tố CHỈ
// áp dụng đơn MỚI — đơn cũ giữ mã đã in. Tạo chi nhánh chạm sequence mã đơn (BE).
const PREFIX_RE = /^[A-Za-z0-9]+$/
const EMPTY = { name: '', address: '', phone: '', order_prefix: '' }

export default function BranchesManage() {
  const { user } = useAuth()
  const canManage = user?.role === 'owner'

  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null) // branch đang sửa (null = tạo)
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)

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

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const openCreate = () => {
    setEditing(null)
    setForm(EMPTY)
    setError('')
    setShowForm(true)
  }

  const openEdit = (b) => {
    setEditing(b)
    setForm({
      name: b.name || '',
      address: b.address || '',
      phone: b.phone || '',
      order_prefix: b.order_prefix || '',
    })
    setError('')
    setShowForm(true)
  }

  const submitForm = async () => {
    const name = form.name.trim()
    const pfx = form.order_prefix.trim()
    if (!name) return setError('Nhập tên chi nhánh.')
    if (editing && !pfx) return setError('Tiền tố không được để trống.')
    if (pfx && !PREFIX_RE.test(pfx)) {
      return setError('Tiền tố chỉ gồm chữ và số, không khoảng trắng/ký tự đặc biệt.')
    }
    setBusy(true)
    setError('')
    try {
      const base = {
        name,
        address: form.address.trim() || null,
        phone: form.phone.trim() || null,
      }
      if (editing) {
        await api.patch(`/branches/${editing.id}`, { ...base, order_prefix: pfx })
      } else {
        // BranchCreate KHÔNG nhận order_prefix (BE đặt mặc định = mã chi nhánh, vd B1).
        // Nếu owner nhập tiền tố tùy biến → PATCH ngay sau khi tạo.
        const created = await api.post('/branches', base)
        if (pfx && pfx !== created.order_prefix) {
          await api.patch(`/branches/${created.id}`, { order_prefix: pfx })
        }
      }
      setShowForm(false)
      await reload()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PREFIX_TAKEN') {
        setError('Tiền tố đã được dùng cho chi nhánh khác.')
      } else if (err instanceof ApiError && err.code === 'INVALID_PREFIX') {
        setError('Tiền tố chỉ gồm chữ và số (không dấu/khoảng trắng), tối đa 16 ký tự.')
      } else {
        setError(err?.message || 'Không lưu được chi nhánh')
      }
    } finally {
      setBusy(false)
    }
  }

  const remove = async (b) => {
    if (!window.confirm(`Xóa chi nhánh "${b.name}"? Chi nhánh sẽ ngừng hoạt động (đơn cũ vẫn giữ).`)) {
      return
    }
    setError('')
    try {
      await api.del(`/branches/${b.id}`)
      await reload()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'BRANCH_HAS_OPEN_SHIFT') {
        setError(`Chi nhánh "${b.name}" còn ca đang mở — đóng ca trước khi xóa.`)
      } else {
        setError(err?.message || 'Không xóa được chi nhánh')
      }
    }
  }

  if (!canManage) {
    return <p className="shift__hint">Chỉ chủ chuỗi mới quản lý chi nhánh.</p>
  }

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Chi nhánh &amp; mã đơn</h2>
        <button className="btn btn--primary btn--sm" onClick={openCreate}>＋ Thêm chi nhánh</button>
      </div>

      <p className="shift__hint">
        Tiền tố ghép số thứ tự thành mã đơn (vd <strong>CH1-00001</strong>). Đổi tiền tố CHỈ
        áp dụng đơn <strong>mới</strong> — đơn cũ giữ mã đã in.
      </p>

      {error && !showForm && <div className="alert alert--error">{error}</div>}

      {loading ? (
        <p className="shift__hint">Đang tải…</p>
      ) : items.length === 0 ? (
        <p className="shift__hint">Chưa có chi nhánh nào.</p>
      ) : (
        <div className="cat-manage-list">
          {items.map((b) => {
            const active = b.status === 'active'
            const meta = [b.address, b.phone].filter(Boolean).join(' · ')
            return (
              <div className={`cat-manage ${active ? '' : 'blk--off'}`} key={b.id}>
                <span className="cat-manage__icon">{b.order_prefix}</span>
                <div className="cat-manage__name" style={{ flex: 1, minWidth: 0 }}>
                  <strong>{b.name}</strong>
                  <div className="shift__hint" style={{ margin: '2px 0 0' }}>
                    {meta ? `${meta} · ` : ''}Mã đơn: {b.order_prefix}-00001
                    {!active && ' · Đã ngừng'}
                  </div>
                </div>
                {active && (
                  <div className="cat-manage__actions">
                    <button className="btn btn--ghost btn--sm" onClick={() => openEdit(b)}>Sửa</button>
                    <button className="btn btn--ghost btn--sm" onClick={() => remove(b)}>Xóa</button>
                  </div>
                )}
              </div>
            )
          })}
        </div>
      )}

      {/* Modal thêm / sửa chi nhánh */}
      {showForm && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal">
            <h3 className="modal__title">{editing ? 'Sửa chi nhánh' : 'Thêm chi nhánh'}</h3>
            <label className="field">
              <span>Tên chi nhánh</span>
              <input className="input" type="text" value={form.name} autoFocus
                placeholder="VD: Chi nhánh Trần Phú"
                onChange={(e) => set('name', e.target.value)} />
            </label>
            <label className="field">
              <span>Địa chỉ (tùy chọn)</span>
              <input className="input" type="text" value={form.address}
                placeholder="VD: 12 Trần Phú, Nha Trang"
                onChange={(e) => set('address', e.target.value)} />
            </label>
            <label className="field">
              <span>Số điện thoại (tùy chọn)</span>
              <input className="input" type="tel" inputMode="numeric" value={form.phone}
                placeholder="VD: 0258..."
                onChange={(e) => set('phone', e.target.value)} />
            </label>
            <label className="field">
              <span>Tiền tố mã đơn{editing ? '' : ' (để trống = tự đặt theo mã chi nhánh)'}</span>
              <input className="input" type="text" value={form.order_prefix} maxLength={16}
                placeholder="VD: CH1"
                onChange={(e) => set('order_prefix', e.target.value)} />
            </label>

            {error && <div className="alert alert--error">{error}</div>}
            <div className="modal__actions modal__actions--row">
              <button className="btn btn--ghost btn--lg" onClick={() => setShowForm(false)} disabled={busy}>Quay lại</button>
              <button className="btn btn--primary btn--lg" onClick={submitForm} disabled={busy}>
                {busy ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo chi nhánh'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
