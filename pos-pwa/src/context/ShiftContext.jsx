import { createContext, useCallback, useContext, useEffect, useState } from 'react'
import { ApiError, api } from '../lib/api'
import { useAuth } from './AuthContext'
import { useBranch } from './BranchContext'

// Trạng thái ca của CHI NHÁNH đang chọn — cho nhãn tab "Ca" động (Mở ca / Đóng ca) (Stage 6.71).
// shiftOpen: null = chưa biết (đang tải / chủ chưa chọn CN) → nhãn "Ca"; true = đang mở → "Đóng ca";
// false = chưa mở → "Mở ca". Cập nhật theo SỰ KIỆN (mở/đóng/mở-lại ca) + refetch khi đổi CN. KHÔNG
// polling. (Provider bọc PER-ROUTE trong Protected nên cũng refetch khi điều hướng → nhãn tự đúng.)
const ShiftContext = createContext({ shiftOpen: null, refresh: () => {}, setShiftOpen: () => {} })

export function ShiftProvider({ children }) {
  const { user } = useAuth()
  const { branchId } = useBranch()
  const isOwner = user?.role === 'owner'
  const [shiftOpen, setShiftOpen] = useState(null)

  const refresh = useCallback(async () => {
    if (isOwner && !branchId) { setShiftOpen(null); return } // chủ chưa chọn CN → chưa xác định
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      await api.get(`/shifts/current${q}`)
      setShiftOpen(true)
    } catch (err) {
      setShiftOpen(err instanceof ApiError && err.status === 404 ? false : null)
    }
  }, [isOwner, branchId])

  // Tải khi vào / khi đổi chi nhánh (ca theo từng CN).
  useEffect(() => { if (user) refresh() }, [user, refresh])

  return (
    <ShiftContext.Provider value={{ shiftOpen, refresh, setShiftOpen }}>
      {children}
    </ShiftContext.Provider>
  )
}

export function useShift() {
  return useContext(ShiftContext)
}
