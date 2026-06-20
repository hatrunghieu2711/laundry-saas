import { useCallback, useEffect, useMemo, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { ApiError, api } from '../lib/api'

// Màn quản lý tài khoản nhân viên (owner + manager) — Stage 5.5.
// Phân quyền theo role + branch. KHÔNG phân quyền chi tiết từng quyền.
// Tài khoản có thể là theo CA (vd "NV ca sáng - Trần Phú", login = "nv_ca_sang").
const ROLE_LABEL = {
  owner: 'Chủ chuỗi',
  manager: 'Quản lý',
  staff: 'Nhân viên',
  shipper: 'Shipper',
}
const ALL_ROLES = ['owner', 'manager', 'staff', 'shipper']
const MANAGER_ROLES = ['staff', 'shipper']
const EMPTY = { full_name: '', phone: '', password: '', role: 'staff', branch_id: '' }

export default function UsersManage() {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'
  const canView = isOwner || user?.role === 'manager'

  const [items, setItems] = useState([])
  const [branches, setBranches] = useState([])
  const [branchFilter, setBranchFilter] = useState('') // owner lọc theo branch
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  // modal thêm/sửa
  const [showForm, setShowForm] = useState(false)
  const [editing, setEditing] = useState(null) // user đang sửa (null = tạo)
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  // modal đặt lại mật khẩu
  const [resetUser, setResetUser] = useState(null)
  const [resetPw, setResetPw] = useState('')

  const roleOptions = isOwner ? ALL_ROLES : MANAGER_ROLES

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const p = await api.get('/users?limit=200')
      setItems(p.items)
    } catch (err) {
      setError(err?.message || 'Không tải được danh sách tài khoản')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  useEffect(() => {
    if (!isOwner) return
    api
      .get('/branches?limit=200')
      .then((p) => setBranches(p.items.filter((b) => b.status === 'active')))
      .catch(() => {})
  }, [isOwner])

  // Quyền thao tác lên 1 tài khoản (khớp backend).
  const canManage = (u) => {
    if (isOwner) return true
    if (user?.role === 'manager') {
      return MANAGER_ROLES.includes(u.role) && u.branch_id === user.branch_id
    }
    return false
  }

  const branchName = (id) =>
    branches.find((b) => b.id === id)?.name ||
    items.find((u) => u.branch_id === id)?.branch_name ||
    (id ? '—' : 'Toàn chuỗi')

  const shown = useMemo(
    () => (branchFilter ? items.filter((u) => u.branch_id === branchFilter) : items),
    [items, branchFilter],
  )

  const openCreate = () => {
    setEditing(null)
    setForm({ ...EMPTY, branch_id: isOwner ? '' : user.branch_id })
    setError('')
    setShowForm(true)
  }

  const openEdit = (u) => {
    setEditing(u)
    setForm({
      full_name: u.full_name,
      phone: u.phone,
      password: '',
      role: u.role,
      branch_id: u.branch_id || '',
    })
    setError('')
    setShowForm(true)
  }

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const submitForm = async () => {
    if (!form.full_name.trim()) return setError('Nhập tên hiển thị.')
    if (!form.phone.trim()) return setError('Nhập tên đăng nhập (SĐT hoặc tên ca).')
    if (!editing && form.password.length < 6) return setError('Mật khẩu tối thiểu 6 ký tự.')
    setBusy(true)
    setError('')
    try {
      const branch_id = form.branch_id || null
      if (editing) {
        await api.patch(`/users/${editing.id}`, {
          full_name: form.full_name.trim(),
          role: form.role,
          branch_id,
        })
      } else {
        await api.post('/users', {
          full_name: form.full_name.trim(),
          phone: form.phone.trim(),
          password: form.password,
          role: form.role,
          branch_id,
        })
      }
      setShowForm(false)
      await reload()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'PHONE_EXISTS') {
        setError('Tên đăng nhập (SĐT) đã tồn tại.')
      } else {
        setError(err?.message || 'Không lưu được tài khoản')
      }
    } finally {
      setBusy(false)
    }
  }

  const submitReset = async () => {
    if (resetPw.length < 6) return setError('Mật khẩu mới tối thiểu 6 ký tự.')
    setBusy(true)
    setError('')
    try {
      await api.post(`/users/${resetUser.id}/reset-password`, { password: resetPw })
      setResetUser(null)
      setResetPw('')
    } catch (err) {
      setError(err?.message || 'Không đặt lại được mật khẩu')
    } finally {
      setBusy(false)
    }
  }

  const toggleLock = async (u) => {
    const next = u.status === 'active' ? 'suspended' : 'active'
    const verb = next === 'suspended' ? 'KHÓA' : 'MỞ'
    if (!window.confirm(`${verb} tài khoản "${u.full_name}"?`)) return
    try {
      await api.patch(`/users/${u.id}/status`, { status: next })
      await reload()
    } catch (err) {
      setError(err?.message || 'Không đổi được trạng thái')
    }
  }

  if (!canView) {
    return <p className="shift__hint">Chỉ chủ chuỗi và quản lý mới xem được màn này.</p>
  }

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Nhân viên</h2>
        <button className="btn btn--primary btn--sm" onClick={openCreate}>＋ Thêm tài khoản</button>
      </div>

      {isOwner && branches.length > 0 && (
        <div className="branch-picker">
          <div className="branch-picker__chips">
            <button className={`chip chip--sm ${!branchFilter ? 'chip--active' : ''}`}
              onClick={() => setBranchFilter('')}>Tất cả CN</button>
            {branches.map((b) => (
              <button key={b.id} className={`chip chip--sm ${branchFilter === b.id ? 'chip--active' : ''}`}
                onClick={() => setBranchFilter(b.id)}>{b.code} · {b.name}</button>
            ))}
          </div>
        </div>
      )}

      {error && !showForm && !resetUser && <div className="alert alert--error">{error}</div>}

      {loading ? (
        <p className="shift__hint">Đang tải…</p>
      ) : shown.length === 0 ? (
        <p className="shift__hint">Chưa có tài khoản nào.</p>
      ) : (
        <div className="cat-manage-list">
          {shown.map((u) => (
            <div className={`cat-manage ${u.status === 'active' ? '' : 'blk--off'}`} key={u.id}>
              <span className={`role-badge role-badge--${u.role}`}>{ROLE_LABEL[u.role] || u.role}</span>
              <div className="cat-manage__name" style={{ flex: 1, minWidth: 0 }}>
                <strong>{u.full_name}</strong>
                {u.in_open_shift && <span className="user-inshift"><span className="udot" />đang trong ca</span>}
                <div className="shift__hint" style={{ margin: '2px 0 0' }}>
                  @{u.phone} · {u.branch_name || (u.branch_id ? '—' : 'Toàn chuỗi')}
                  {u.status === 'suspended' && ' · Đã khóa'}
                  {u.status === 'inactive' && ' · Đã xóa'}
                </div>
              </div>
              {canManage(u) && (
                <div className="cat-manage__actions">
                  <button className="btn btn--ghost btn--sm" onClick={() => openEdit(u)}>Sửa</button>
                  <button className="btn btn--ghost btn--sm" onClick={() => { setResetUser(u); setResetPw(''); setError('') }}>Đặt lại MK</button>
                  {u.id !== user.id && (
                    <button className="btn btn--ghost btn--sm" onClick={() => toggleLock(u)}>
                      {u.status === 'active' ? 'Khóa' : 'Mở'}
                    </button>
                  )}
                </div>
              )}
            </div>
          ))}
        </div>
      )}

      {/* Modal thêm / sửa */}
      {showForm && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal">
            <h3 className="modal__title">{editing ? 'Sửa tài khoản' : 'Thêm tài khoản'}</h3>
            <label className="field">
              <span>Tên hiển thị</span>
              <input className="input" type="text" value={form.full_name}
                placeholder="VD: NV ca sáng - Trần Phú"
                onChange={(e) => set('full_name', e.target.value)} />
            </label>
            <label className="field">
              <span>Tên đăng nhập (SĐT hoặc tên ca)</span>
              <input className="input" type="text" value={form.phone} disabled={!!editing}
                placeholder="VD: nv_ca_sang hoặc 0905..."
                onChange={(e) => set('phone', e.target.value)} />
            </label>
            {!editing && (
              <label className="field">
                <span>Mật khẩu (tối thiểu 6 ký tự)</span>
                <input className="input" type="text" value={form.password}
                  placeholder="Mật khẩu đăng nhập"
                  onChange={(e) => set('password', e.target.value)} />
              </label>
            )}
            <label className="field">
              <span>Vai trò</span>
              <select className="input" value={form.role} disabled={editing?.role === 'owner'}
                onChange={(e) => set('role', e.target.value)}>
                {(editing?.role === 'owner' ? ALL_ROLES : roleOptions).map((r) => (
                  <option key={r} value={r}>{ROLE_LABEL[r]}</option>
                ))}
              </select>
            </label>
            <label className="field">
              <span>Chi nhánh</span>
              <select className="input" value={form.branch_id} disabled={!isOwner}
                onChange={(e) => set('branch_id', e.target.value)}>
                <option value="">— Không gắn chi nhánh (toàn chuỗi)</option>
                {(isOwner ? branches : []).map((b) => (
                  <option key={b.id} value={b.id}>{b.code} · {b.name}</option>
                ))}
                {!isOwner && <option value={user.branch_id}>{user.branch_name || 'Chi nhánh của tôi'}</option>}
              </select>
            </label>

            {error && <div className="alert alert--error">{error}</div>}
            <div className="modal__actions modal__actions--row">
              <button className="btn btn--ghost btn--lg" onClick={() => setShowForm(false)} disabled={busy}>Quay lại</button>
              <button className="btn btn--primary btn--lg" onClick={submitForm} disabled={busy}>
                {busy ? 'Đang lưu…' : editing ? 'Lưu' : 'Tạo tài khoản'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Modal đặt lại mật khẩu */}
      {resetUser && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal">
            <h3 className="modal__title">Đặt lại mật khẩu</h3>
            <p className="shift__hint">Tài khoản: <strong>{resetUser.full_name}</strong> (@{resetUser.phone})</p>
            <label className="field">
              <span>Mật khẩu mới (tối thiểu 6 ký tự)</span>
              <input className="input" type="text" value={resetPw} autoFocus
                onChange={(e) => setResetPw(e.target.value)} />
            </label>
            {error && <div className="alert alert--error">{error}</div>}
            <div className="modal__actions modal__actions--row">
              <button className="btn btn--ghost btn--lg" onClick={() => setResetUser(null)} disabled={busy}>Quay lại</button>
              <button className="btn btn--primary btn--lg" onClick={submitReset} disabled={busy}>
                {busy ? 'Đang lưu…' : 'Đặt lại'}
              </button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
