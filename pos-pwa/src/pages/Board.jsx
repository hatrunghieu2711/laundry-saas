import { useCallback, useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { useTopbarSlot } from '../context/TopbarSlotContext'
import { api } from '../lib/api'

// Dashboard "Đơn hàng" (Stage 6.10): 3 cột thao tác tại tiệm.
//   - GỘP washing + drying → "Đang xử lý".
//   - BỎ "Đã giao" khỏi dashboard (tra ở tab Tra cứu — Stage 6.11).
//   - Thẻ = KHUNG RỖNG (layout thẻ thiết kế stage sau), click → chi tiết đơn.
const COLUMNS = [
  { key: 'created', label: 'Mới nhận', statuses: ['created'] },
  { key: 'processing', label: 'Đang xử lý', statuses: ['washing', 'drying'] },
  { key: 'ready', label: 'Sẵn sàng', statuses: ['ready'] },
]
const REFRESH_MS = 30000

export default function Board() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'
  const { branchId } = useBranch()
  const { slotEl } = useTopbarSlot()

  const [search, setSearch] = useState('')
  const [q, setQ] = useState('')
  const [board, setBoard] = useState(null)
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)
  const [updatedAt, setUpdatedAt] = useState(null)

  // debounce search → q
  useEffect(() => {
    const t = setTimeout(() => setQ(search.trim()), 350)
    return () => clearTimeout(t)
  }, [search])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const p = new URLSearchParams()
      if (isOwner && branchId) p.set('branch_id', branchId)
      if (q) p.set('q', q)
      const d = await api.get(`/orders/board?${p}`)
      setBoard(d)
      setUpdatedAt(new Date())
    } catch (err) {
      setError(err?.message || 'Không tải được đơn hàng')
    } finally {
      setLoading(false)
    }
  }, [isOwner, branchId, q])

  useEffect(() => {
    load()
  }, [load])

  // Tự refresh định kỳ (đứng ở dashboard).
  useEffect(() => {
    const t = setInterval(load, REFRESH_MS)
    return () => clearInterval(t)
  }, [load])

  const cols = board?.columns || {}
  // Gộp đơn theo cột (washing+drying), sắp lại theo giờ hẹn giao tăng dần.
  const columnItems = COLUMNS.map((col) => {
    const items = col.statuses.flatMap((s) => cols[s] || [])
    items.sort((a, b) => {
      if (a.pickup_at < b.pickup_at) return -1
      if (a.pickup_at > b.pickup_at) return 1
      return 0
    })
    return { ...col, items }
  })
  // Thống kê tính CLIENT-SIDE từ ĐÚNG các đơn đang hiển thị (bỏ delivered) → nhất
  // quán với số thẻ thấy được.
  const shown = columnItems.flatMap((c) => c.items)
  const stat = {
    total: shown.length,
    unpaid: shown.filter((o) => o.payment_status === 'unpaid' || o.payment_status === 'partial').length,
    paid: shown.filter((o) => o.payment_status === 'paid').length,
    debt: shown.filter((o) => o.payment_status === 'debt').length,
  }

  // Search nhỏ + nút Làm mới → teleport lên thanh trên cùng (gộp chung 1 thanh).
  const topControls = (
    <div className="topbar-actions">
      <input
        className="topbar-actions__search"
        type="search"
        placeholder="🔍 Tìm mã đơn / tên / SĐT…"
        value={search}
        onChange={(e) => setSearch(e.target.value)}
        aria-label="Tìm đơn"
      />
      <button className="topbar-actions__refresh" onClick={load} disabled={loading}>
        {loading ? '…' : '↻ Làm mới'}
      </button>
    </div>
  )

  return (
    <div className="board">
      {slotEl && createPortal(topControls, slotEl)}

      <div className="board-stats">
        <span>Ở tiệm <b>{stat.total}</b></span>
        <span className="board-stats__dot">·</span>
        <span>Chưa thu <b className="board-stats__warn">{stat.unpaid}</b></span>
        <span className="board-stats__dot">·</span>
        <span>Đã thu <b className="board-stats__success">{stat.paid}</b></span>
        <span className="board-stats__dot">·</span>
        <span>Nợ <b>{stat.debt}</b></span>
        <div className="board-stats__spacer" />
        {updatedAt && (
          <span className="board-stats__updated">
            Cập nhật {String(updatedAt.getHours()).padStart(2, '0')}:
            {String(updatedAt.getMinutes()).padStart(2, '0')}
          </span>
        )}
      </div>

      {error && <div className="alert alert--error">{error}</div>}

      <div className="board3">
        {columnItems.map((col) => (
          <section className="board3__col" key={col.key}>
            <div className="board3__col-head">
              <span className="board3__col-title">{col.label}</span>
              <span className="board3__col-count">{col.items.length}</span>
            </div>
            <div className="board3__cards">
              {col.items.map((o) => (
                <button
                  key={o.id}
                  className="board3__card-ph"
                  title={o.order_code}
                  aria-label={`Đơn ${o.order_code}`}
                  onClick={() => navigate(`/orders/${o.id}`)}
                />
              ))}
            </div>
          </section>
        ))}
      </div>
    </div>
  )
}
