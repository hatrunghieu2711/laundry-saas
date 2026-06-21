import { useCallback, useEffect, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { api } from '../lib/api'

// Màn "Dịch vụ theo chi nhánh" (owner): chọn CN → toggle Hiện/Ẩn từng dịch vụ.
// Mặc định Hiện (dịch vụ KHÔNG nằm trong danh sách ẩn của CN). Ẩn = display-only:
// chỉ loại khỏi màn tạo đơn ở CN đó; giá chung, đơn cũ không đổi.
export default function BranchServiceVisibility() {
  const { user } = useAuth()
  const canManage = user?.role === 'owner'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState('')
  const [services, setServices] = useState([])
  const [hidden, setHidden] = useState(() => new Set()) // service_id đang ẩn ở CN chọn
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [savingId, setSavingId] = useState(null)

  // Tải chi nhánh + bảng dịch vụ (active) một lần.
  useEffect(() => {
    if (!canManage) {
      setLoading(false)
      return
    }
    Promise.all([api.get('/branches?limit=200'), api.get('/services?limit=200')])
      .then(([bp, sp]) => {
        const active = bp.items.filter((b) => b.status === 'active')
        setBranches(active)
        setServices(sp.items)
        if (active.length) setBranchId(active[0].id)
      })
      .catch((err) => setError(err?.message || 'Không tải được dữ liệu'))
      .finally(() => setLoading(false))
  }, [canManage])

  // Tải danh sách ẩn của CN đang chọn.
  const loadHidden = useCallback(async (bid) => {
    if (!bid) return
    setError('')
    try {
      const r = await api.get(`/branches/${bid}/hidden-services`)
      setHidden(new Set(r.hidden_service_ids))
    } catch (err) {
      setError(err?.message || 'Không tải được trạng thái ẩn/hiện')
    }
  }, [])

  useEffect(() => {
    loadHidden(branchId)
  }, [branchId, loadHidden])

  const toggle = async (svc) => {
    const isHidden = hidden.has(svc.id)
    const nextHidden = !isHidden // bấm "Ẩn" khi đang hiện → ẩn; ngược lại
    setSavingId(svc.id)
    setError('')
    try {
      await api.put(`/branches/${branchId}/hidden-services/${svc.id}`, { hidden: nextHidden })
      setHidden((prev) => {
        const n = new Set(prev)
        if (nextHidden) n.add(svc.id)
        else n.delete(svc.id)
        return n
      })
    } catch (err) {
      setError(err?.message || 'Không lưu được')
    } finally {
      setSavingId(null)
    }
  }

  if (!canManage) {
    return <p className="shift__hint">Chỉ chủ chuỗi mới quản lý dịch vụ theo chi nhánh.</p>
  }
  if (loading) {
    return <p className="shift__hint">Đang tải…</p>
  }

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Dịch vụ theo chi nhánh</h2>
        {branches.length > 0 && (
          <select
            className="input"
            style={{ maxWidth: 220 }}
            value={branchId}
            onChange={(e) => setBranchId(e.target.value)}
            aria-label="Chọn chi nhánh"
          >
            {branches.map((b) => (
              <option key={b.id} value={b.id}>{b.order_prefix} · {b.name}</option>
            ))}
          </select>
        )}
      </div>

      <p className="shift__hint">
        Tắt (ẩn) dịch vụ ở chi nhánh đang chọn → màn tạo đơn của CN đó KHÔNG hiện dịch vụ này.
        Giá <strong>chung</strong>; đơn cũ không đổi. Mặc định mọi dịch vụ đều hiện.
      </p>

      {error && <div className="alert alert--error">{error}</div>}

      {branches.length === 0 ? (
        <p className="shift__hint">Chưa có chi nhánh nào.</p>
      ) : services.length === 0 ? (
        <p className="shift__hint">Chưa có dịch vụ nào trong bảng giá.</p>
      ) : (
        <div className="cat-manage-list">
          {services.map((s) => {
            const isHidden = hidden.has(s.id)
            return (
              <div className={`cat-manage ${isHidden ? 'blk--off' : ''}`} key={s.id}>
                <div className="cat-manage__name" style={{ flex: 1, minWidth: 0 }}>
                  <strong>{s.name}</strong>
                  <div className="shift__hint" style={{ margin: '2px 0 0' }}>
                    {isHidden ? 'Đang ẩn ở CN này' : 'Đang hiện'}
                  </div>
                </div>
                <div className="cat-manage__actions">
                  <button
                    className="btn btn--ghost btn--sm"
                    onClick={() => toggle(s)}
                    disabled={savingId === s.id}
                  >
                    {savingId === s.id ? '…' : isHidden ? 'Hiện' : 'Ẩn'}
                  </button>
                </div>
              </div>
            )
          })}
        </div>
      )}
    </div>
  )
}
