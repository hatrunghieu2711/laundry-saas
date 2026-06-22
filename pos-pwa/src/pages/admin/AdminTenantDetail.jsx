import { useCallback, useEffect, useState } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { ApiError, api } from '../../lib/api'
import { formatDateTime } from '../../lib/format'

async function copy(text) {
  try {
    await navigator.clipboard.writeText(text)
  } catch {
    /* bỏ qua nếu clipboard không khả dụng */
  }
}

export default function AdminTenantDetail() {
  const { id } = useParams()
  const navigate = useNavigate()
  const [t, setT] = useState(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [saveMsg, setSaveMsg] = useState('')
  const [saveErr, setSaveErr] = useState('')
  const [busy, setBusy] = useState(false)

  const [resetResult, setResetResult] = useState(null) // {owner_phone, temp_password}
  const [resetErr, setResetErr] = useState('')

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.admin.getTenant(id)
      setT(data)
      setName(data.name)
      setSlug(data.slug)
    } catch (e) {
      setError(e?.message || 'Không tải được cửa hàng')
    } finally {
      setLoading(false)
    }
  }, [id])

  useEffect(() => {
    load()
  }, [load])

  const saveInfo = async () => {
    setBusy(true)
    setSaveMsg('')
    setSaveErr('')
    try {
      const res = await api.admin.updateTenant(id, { name: name.trim(), slug: slug.trim() })
      setT((cur) => ({ ...cur, name: res.name, slug: res.slug }))
      setSaveMsg(
        res.slug_changed
          ? 'Đã lưu. ⚠️ Đổi mã cửa hàng → nhân viên phải nhập MÃ MỚI khi đăng nhập.'
          : 'Đã lưu.',
      )
    } catch (e) {
      if (e instanceof ApiError && e.code === 'SLUG_EXISTS') {
        setSaveErr('Mã cửa hàng đã tồn tại — chọn mã khác.')
      } else if (e instanceof ApiError && e.status === 422) {
        setSaveErr('Mã cửa hàng chỉ gồm chữ thường, số và dấu gạch ngang.')
      } else {
        setSaveErr(e?.message || 'Không lưu được')
      }
    } finally {
      setBusy(false)
    }
  }

  const toggleLock = async () => {
    const locking = t.status === 'active'
    const verb = locking ? 'KHÓA' : 'MỞ'
    if (!window.confirm(`${verb} cửa hàng "${t.name}"?${locking ? ' Mọi người sẽ bị đăng xuất trong ≤30 phút.' : ''}`)) return
    setBusy(true)
    setError('')
    try {
      const res = locking ? await api.admin.lockTenant(id) : await api.admin.unlockTenant(id)
      setT((cur) => ({ ...cur, status: res.status }))
    } catch (e) {
      setError(e?.message || 'Không đổi được trạng thái')
    } finally {
      setBusy(false)
    }
  }

  const resetOwner = async () => {
    if (!window.confirm('Đặt lại mật khẩu chủ tiệm? Mật khẩu cũ sẽ ngừng hoạt động.')) return
    setBusy(true)
    setResetErr('')
    setResetResult(null)
    try {
      const res = await api.admin.resetOwnerPassword(id)
      setResetResult(res)
    } catch (e) {
      if (e instanceof ApiError && e.code === 'NO_OWNER') {
        setResetErr('Cửa hàng không có chủ tiệm đang hoạt động.')
      } else if (e instanceof ApiError && e.code === 'MULTIPLE_OWNERS') {
        setResetErr('Cửa hàng có nhiều chủ tiệm — liên hệ kỹ thuật để xử lý.')
      } else {
        setResetErr(e?.message || 'Không đặt lại được mật khẩu')
      }
    } finally {
      setBusy(false)
    }
  }

  if (loading) return <p className="shift__hint">Đang tải…</p>
  if (error) return <div className="alert alert--error">{error}</div>
  if (!t) return null

  const locked = t.status !== 'active'

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">{t.name}</h2>
        <button className="btn btn--ghost btn--sm" onClick={() => navigate('/admin')}>← Danh sách</button>
      </div>

      <p className="shift__hint" style={{ marginTop: -4 }}>
        {t.n_branches} chi nhánh · {t.n_users} nhân viên ·{' '}
        {t.last_order_at ? `đơn gần nhất ${formatDateTime(t.last_order_at)}` : 'chưa có đơn'} ·{' '}
        {locked ? 'Đang tạm ngưng' : 'Đang hoạt động'}
      </p>

      {/* Thông tin */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Thông tin</div>
        <label className="field">
          <span>Tên cửa hàng</span>
          <input className="input" type="text" value={name} onChange={(e) => setName(e.target.value)} />
        </label>
        <label className="field">
          <span>Mã cửa hàng (slug)</span>
          <input className="input" type="text" value={slug} autoCapitalize="none" autoCorrect="off"
            spellCheck={false} onChange={(e) => setSlug(e.target.value)} />
          <span className="field-note">Đổi mã → nhân viên phải nhập mã mới khi đăng nhập.</span>
        </label>
        {saveErr && <div className="alert alert--error">{saveErr}</div>}
        {saveMsg && <div className="alert alert--success">{saveMsg}</div>}
        <button className="btn btn--primary btn--sm" onClick={saveInfo} disabled={busy}>
          {busy ? 'Đang lưu…' : 'Lưu thông tin'}
        </button>
      </div>

      {/* Thao tác */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Thao tác</div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8 }}>
          <button className="btn btn--ghost btn--sm" onClick={toggleLock} disabled={busy}>
            {locked ? 'Mở cửa hàng' : 'Khóa cửa hàng'}
          </button>
          <button className="btn btn--ghost btn--sm" onClick={resetOwner} disabled={busy}>
            Đặt lại MK chủ tiệm
          </button>
        </div>
        <p className="shift__hint" style={{ margin: '8px 0 0' }}>
          Khóa → mọi người của cửa hàng bị đăng xuất trong ≤30 phút (thu hồi phiên).
        </p>

        {resetErr && <div className="alert alert--error" style={{ marginTop: 10 }}>{resetErr}</div>}
        {resetResult && (
          <div className="alert alert--success" style={{ marginTop: 10 }}>
            <div><strong>Đã đặt lại mật khẩu.</strong> Chỉ hiện 1 lần — lưu lại NGAY.</div>
            <div style={{ marginTop: 4 }}>SĐT chủ tiệm: <strong>{resetResult.owner_phone}</strong></div>
            <div style={{ display: 'flex', alignItems: 'center', gap: 8, marginTop: 4 }}>
              <span>Mật khẩu tạm: <strong>{resetResult.temp_password}</strong></span>
              <button className="btn btn--ghost btn--sm" onClick={() => copy(resetResult.temp_password)}>Sao chép</button>
            </div>
          </div>
        )}
      </div>
    </div>
  )
}
