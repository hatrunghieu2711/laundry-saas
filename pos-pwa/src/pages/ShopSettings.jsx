import { useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'

// Cài đặt tiệm (owner): đổi TÊN TIỆM (tenant name). Lấy tên hiện tại qua
// GET /tenants/{id}, lưu qua PATCH /tenants/{id} (BE owner-only + _ensure_own_tenant).
// Hiển thị MÃ CỬA HÀNG (slug) read-only — nhân viên dùng mã này để đăng nhập.
export default function ShopSettings() {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'
  const tenantId = user?.tenant_id

  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)

  useEffect(() => {
    if (!isOwner || !tenantId) {
      setLoading(false)
      return undefined
    }
    let alive = true
    api
      .get(`/tenants/${tenantId}`)
      .then((t) => {
        if (!alive) return
        setName(t.name || '')
        setSlug(t.slug || '')
      })
      .catch((err) => {
        if (alive) setError(err?.message || 'Không tải được thông tin tiệm')
      })
      .finally(() => {
        if (alive) setLoading(false)
      })
    return () => {
      alive = false
    }
  }, [isOwner, tenantId])

  const save = async (e) => {
    e.preventDefault()
    const nm = name.trim()
    setError('')
    setDone(false)
    if (!nm) {
      setError('Nhập tên tiệm.')
      return
    }
    setSaving(true)
    try {
      const t = await api.patch(`/tenants/${tenantId}`, { name: nm })
      setName(t.name || nm)
      setDone(true)
    } catch (err) {
      setError(err?.message || 'Không lưu được tên tiệm')
    } finally {
      setSaving(false)
    }
  }

  if (!isOwner) {
    return <p className="shift__hint">Chỉ chủ chuỗi mới đổi tên tiệm.</p>
  }
  if (loading) {
    return <p className="shift__hint">Đang tải…</p>
  }

  return (
    <div className="shift">
      <form className="shift__card" onSubmit={save} style={{ maxWidth: 460 }}>
        <h2 className="shift__card-title">Cài đặt tiệm</h2>

        <label className="field">
          <span>Tên tiệm</span>
          <input
            className="input"
            type="text"
            value={name}
            maxLength={255}
            required
            autoFocus
            onChange={(e) => setName(e.target.value)}
          />
        </label>

        <label className="field">
          <span>Mã cửa hàng (nhân viên dùng để đăng nhập) — không đổi</span>
          <input className="input" type="text" value={slug} disabled readOnly />
        </label>

        {error && <div className="alert alert--error">{error}</div>}
        {done && <div className="alert alert--success">Đã lưu tên tiệm.</div>}

        <button className="btn btn--primary btn--block" type="submit" disabled={saving}>
          {saving ? 'Đang lưu…' : 'Lưu'}
        </button>
      </form>
    </div>
  )
}
