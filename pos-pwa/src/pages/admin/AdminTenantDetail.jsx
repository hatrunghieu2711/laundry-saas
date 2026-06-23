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

  // Gói dịch vụ. ⚠️ GET detail KHÔNG trả gói hiện tại (chỉ n_branches) → `sub` chỉ có
  // sau khi Lưu (từ response PUT). Trước đó hiển thị tối thiểu (n_branches + form chọn gói).
  const [plans, setPlans] = useState([])
  const [sub, setSub] = useState(null) // {plan_name, effective_max_branches, custom_max_branches, plan_id}
  const [planId, setPlanId] = useState('')
  const [customMax, setCustomMax] = useState('')
  const [planMsg, setPlanMsg] = useState('')
  const [planErr, setPlanErr] = useState('')
  const [planBusy, setPlanBusy] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const [data, planList] = await Promise.all([
        api.admin.getTenant(id),
        api.admin.listPlans().catch(() => []),
      ])
      setT(data)
      setName(data.name)
      setSlug(data.slug)
      setPlans(planList)
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

  const savePlan = async () => {
    if (!planId) return setPlanErr('Chọn gói trước khi lưu.')
    const custom = customMax.trim() ? parseInt(customMax.trim(), 10) : null
    if (custom !== null && (Number.isNaN(custom) || custom < 1)) {
      return setPlanErr('Giới hạn tùy chỉnh phải là số nguyên ≥ 1.')
    }
    const selected = plans.find((p) => p.id === planId)
    const newLimit = custom !== null ? custom : selected?.max_branches ?? 0
    // ⚠️ Cảnh báo hạ gói: giới hạn mới < số CN đang dùng (backend KHÔNG xóa CN, chỉ chặn thêm).
    if (newLimit < t.n_branches) {
      const ok = window.confirm(
        `Cửa hàng đang dùng ${t.n_branches} chi nhánh; giới hạn mới (${newLimit}) thấp hơn — ` +
        'sẽ KHÔNG thêm được CN mới (chi nhánh hiện có vẫn giữ). Vẫn lưu?',
      )
      if (!ok) return
    }
    setPlanBusy(true)
    setPlanErr('')
    setPlanMsg('')
    try {
      const body = { plan_id: planId }
      if (custom !== null) body.custom_max_branches = custom
      const res = await api.admin.setSubscription(id, body)
      setSub(res)
      setPlanId(res.plan_id)
      setCustomMax(res.custom_max_branches != null ? String(res.custom_max_branches) : '')
      setPlanMsg('Đã lưu gói.')
    } catch (e) {
      setPlanErr(e?.message || 'Không lưu được gói')
    } finally {
      setPlanBusy(false)
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

      {/* Gói dịch vụ */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Gói dịch vụ</div>

        {/* Trạng thái hiện tại (nền nhạt). GET detail không trả gói → chỉ có sau khi Lưu. */}
        <div style={{
          background: 'var(--bg)', border: '1px solid var(--line)',
          borderRadius: 8, padding: '10px 12px', marginBottom: 12,
        }}>
          {sub ? (
            <>
              Đang dùng: <strong>{sub.plan_name}</strong> · {t.n_branches}/{sub.effective_max_branches} chi nhánh
              {sub.custom_max_branches != null && <span className="shift__hint"> (tùy chỉnh)</span>}
            </>
          ) : (
            <>Số chi nhánh đang dùng: <strong>{t.n_branches}</strong>. Chọn gói bên dưới để đặt giới hạn.</>
          )}
        </div>

        <label className="field">
          <span>Gói</span>
          <select className="input" value={planId} onChange={(e) => setPlanId(e.target.value)}>
            <option value="">— Chọn gói —</option>
            {plans.map((p) => (
              <option key={p.id} value={p.id}>{p.name} ({p.max_branches} CN)</option>
            ))}
          </select>
        </label>
        <label className="field">
          <span>Giới hạn tùy chỉnh (số chi nhánh)</span>
          <input className="input" type="number" min="1" value={customMax}
            placeholder="Bỏ trống = theo gói"
            onChange={(e) => setCustomMax(e.target.value)} />
          <span className="field-note">Bỏ trống = dùng số của gói; nhập số cho ca cần nhiều CN hơn.</span>
        </label>
        {planErr && <div className="alert alert--error">{planErr}</div>}
        {planMsg && <div className="alert alert--success">{planMsg}</div>}
        <button className="btn btn--primary btn--sm" onClick={savePlan} disabled={planBusy}>
          {planBusy ? 'Đang lưu…' : 'Lưu gói'}
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
