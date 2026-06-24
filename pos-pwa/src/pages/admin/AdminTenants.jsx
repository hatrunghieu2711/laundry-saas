import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ApiError, api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'

const EMPTY = {
  name: '', slug: '', owner_full_name: '', owner_phone: '', owner_password: '', branch_name: '',
}

function StatusBadge({ status }) {
  const active = status === 'active'
  return (
    <span
      style={{
        fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 999,
        background: active ? '#e3f6e8' : '#fde8e8',
        color: active ? '#16794a' : '#b42318',
      }}
    >
      {active ? 'Hoạt động' : 'Tạm ngưng'}
    </span>
  )
}

// Badge HẠN gói — liếc nhanh tenant sắp/đã hết hạn. active xám · warning vàng ·
// grace cam · expired đỏ (khớp expiry_status từ BE).
const _EXPIRY_BADGE = {
  warning: { bg: '#fef9c3', color: '#854d0e' },
  grace: { bg: '#ffedd5', color: '#9a3412' },
  expired: { bg: '#fde8e8', color: '#b42318' },
  active: { bg: '#f1f5f9', color: '#475569' },
}

function ExpiryBadge({ tenant }) {
  const st = tenant.expiry_status || 'active'
  const n = tenant.days_left
  let label
  if (!tenant.expires_at) label = 'Hạn: vô hạn'
  else if (st === 'expired') label = 'Hết hạn'
  else if (st === 'grace') label = `Ân hạn ${n}n`
  else if (st === 'warning') label = `Còn ${n}n`
  else label = `Còn ${n}n`
  const c = _EXPIRY_BADGE[st] || _EXPIRY_BADGE.active
  return (
    <span style={{
      fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 999,
      background: c.bg, color: c.color, marginLeft: 6,
    }}>
      {label}
    </span>
  )
}

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    /* clipboard không khả dụng — bỏ qua */
  }
}

export default function AdminTenants() {
  const navigate = useNavigate()
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [showForm, setShowForm] = useState(false)
  const [form, setForm] = useState(EMPTY)
  const [busy, setBusy] = useState(false)
  const [formError, setFormError] = useState('')
  const [created, setCreated] = useState(null) // {slug, owner_phone, temp_password, branch_code}

  const reload = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      setItems(await api.admin.listTenants())
    } catch (e) {
      setError(e?.message || 'Không tải được danh sách cửa hàng')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    reload()
  }, [reload])

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }))

  const openCreate = () => {
    setForm(EMPTY)
    setCreated(null)
    setFormError('')
    setShowForm(true)
  }

  const submitCreate = async () => {
    if (!form.name.trim()) return setFormError('Nhập tên cửa hàng.')
    if (!form.slug.trim()) return setFormError('Nhập mã cửa hàng (slug).')
    if (!form.owner_full_name.trim()) return setFormError('Nhập tên chủ tiệm.')
    if (!form.owner_phone.trim()) return setFormError('Nhập SĐT chủ tiệm.')
    setBusy(true)
    setFormError('')
    try {
      const body = {
        name: form.name.trim(),
        slug: form.slug.trim(),
        owner_full_name: form.owner_full_name.trim(),
        owner_phone: form.owner_phone.trim(),
      }
      if (form.owner_password) body.owner_password = form.owner_password
      if (form.branch_name.trim()) body.branch_name = form.branch_name.trim()
      const res = await api.admin.createTenant(body)
      setCreated(res)
      await reload()
    } catch (e) {
      if (e instanceof ApiError && e.code === 'SLUG_EXISTS') {
        setFormError('Mã cửa hàng đã tồn tại — chọn mã khác.')
      } else if (e instanceof ApiError && e.status === 422) {
        setFormError('Mã cửa hàng chỉ gồm chữ thường, số và dấu gạch ngang.')
      } else {
        setFormError(e?.message || 'Không tạo được cửa hàng')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Cửa hàng</h2>
        <button className="btn btn--primary btn--sm" onClick={openCreate}>＋ Tạo cửa hàng</button>
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      {loading ? (
        <p className="shift__hint">Đang tải…</p>
      ) : items.length === 0 ? (
        <p className="shift__hint">Chưa có cửa hàng nào.</p>
      ) : (
        <div className="cat-group">
          {items.map((t) => (
            <div className="cat-item" key={t.id}>
              <div className="cat-item__main">
                <div className="cat-item__name">
                  {t.name} <StatusBadge status={t.status} /><ExpiryBadge tenant={t} />
                </div>
                <div className="cat-item__meta">
                  {t.slug} · {t.n_branches} CN · {t.n_users} nhân viên ·{' '}
                  {t.last_order_at ? `đơn gần nhất ${formatDateTime(t.last_order_at)}` : 'chưa có đơn'}
                </div>
              </div>
              <button
                className="btn btn--ghost btn--sm"
                onClick={() => navigate(`/admin/tenants/${t.id}`)}
              >
                Chi tiết
              </button>
            </div>
          ))}
        </div>
      )}

      {/* Modal tạo cửa hàng */}
      {showForm && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal">
            <h3 className="modal__title">Tạo cửa hàng</h3>

            {created ? (
              <>
                <div className="alert alert--success">
                  <div><strong>Đã tạo cửa hàng.</strong> Mật khẩu chỉ hiện 1 lần — lưu lại NGAY.</div>
                  <div style={{ marginTop: 8 }}>Mã cửa hàng: <strong>{created.slug}</strong></div>
                  <div>SĐT chủ tiệm: <strong>{created.owner_phone}</strong></div>
                  <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
                    <span>Mật khẩu tạm: <strong>{created.temp_password}</strong></span>
                    <button className="btn btn--ghost btn--sm" onClick={() => copy(created.temp_password)}>Sao chép</button>
                  </div>
                </div>
                <div className="modal__actions modal__actions--row">
                  <button className="btn btn--primary btn--lg" onClick={() => setShowForm(false)}>Xong</button>
                </div>
              </>
            ) : (
              <>
                <label className="field">
                  <span>Tên cửa hàng</span>
                  <input className="input" type="text" value={form.name}
                    placeholder="VD: Giặt Ủi Sạch Thơm" onChange={(e) => set('name', e.target.value)} />
                </label>
                <label className="field">
                  <span>Mã cửa hàng (slug — nhân viên gõ khi đăng nhập)</span>
                  <input className="input" type="text" value={form.slug} autoCapitalize="none"
                    autoCorrect="off" spellCheck={false}
                    placeholder="vd: sach-thom" onChange={(e) => set('slug', e.target.value)} />
                </label>
                <label className="field">
                  <span>Tên chủ tiệm</span>
                  <input className="input" type="text" value={form.owner_full_name}
                    placeholder="VD: Chị Lan" onChange={(e) => set('owner_full_name', e.target.value)} />
                </label>
                <label className="field">
                  <span>SĐT chủ tiệm (tên đăng nhập)</span>
                  <input className="input" type="text" value={form.owner_phone}
                    placeholder="0905..." onChange={(e) => set('owner_phone', e.target.value)} />
                </label>
                <label className="field">
                  <span>Mật khẩu chủ tiệm (bỏ trống → tự sinh)</span>
                  <input className="input" type="text" value={form.owner_password}
                    placeholder="Để trống để hệ thống sinh ngẫu nhiên"
                    onChange={(e) => set('owner_password', e.target.value)} />
                </label>
                <label className="field">
                  <span>Tên chi nhánh đầu (bỏ trống → "Chi nhánh 1")</span>
                  <input className="input" type="text" value={form.branch_name}
                    placeholder="Chi nhánh 1" onChange={(e) => set('branch_name', e.target.value)} />
                </label>

                {formError && <div className="alert alert--error">{formError}</div>}
                <div className="modal__actions modal__actions--row">
                  <button className="btn btn--ghost btn--lg" onClick={() => setShowForm(false)} disabled={busy}>Quay lại</button>
                  <button className="btn btn--primary btn--lg" onClick={submitCreate} disabled={busy}>
                    {busy ? 'Đang tạo…' : 'Tạo cửa hàng'}
                  </button>
                </div>
              </>
            )}
          </div>
        </div>
      )}
    </div>
  )
}
