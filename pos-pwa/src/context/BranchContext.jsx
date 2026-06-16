import { createContext, useContext, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { useAuth } from './AuthContext'

// Chi nhánh đang chọn — dùng chung cho HEADER (dropdown) và màn Tạo đơn
// (Stage 6.6.1). Trước đây state này nằm trong OrderNew; chuyển lên context để
// bộ chọn CN nằm trên header (cạnh ☰) thay vì 1 hàng riêng. LOGIC giữ nguyên:
//   - Chủ (owner): branchId = null đến khi chọn; tự chọn nếu chỉ 1 CN.
//   - Nhân viên: cố định theo branch của tài khoản (không đổi).
const BranchContext = createContext({ branchId: null, setBranchId: () => {}, branches: [] })

export function BranchProvider({ children }) {
  const { user } = useAuth()
  const isOwner = user?.role === 'owner'
  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(isOwner ? null : user?.branch_id || null)

  useEffect(() => {
    if (!isOwner) return
    api
      .get('/branches?limit=200')
      .then((p) => {
        const active = p.items.filter((b) => b.status === 'active')
        setBranches(active)
        if (active.length === 1) setBranchId(active[0].id)
      })
      .catch(() => {})
  }, [isOwner])

  return (
    <BranchContext.Provider value={{ branchId, setBranchId, branches }}>
      {children}
    </BranchContext.Provider>
  )
}

export function useBranch() {
  return useContext(BranchContext)
}
