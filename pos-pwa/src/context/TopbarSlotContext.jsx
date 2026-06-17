import { createContext, useContext, useState } from 'react'

// Thanh trên cùng (Layout) chừa 1 ô trống; TRANG hiện hành "teleport" controls
// (search + làm mới) vào ô đó qua portal → gộp chung 1 thanh 48px (Stage 6.10).
// Dùng portal (thay vì truyền JSX qua context) để state của trang KHÔNG bị stale.
const TopbarSlotContext = createContext({ slotEl: null, setSlotEl: () => {} })

export function TopbarSlotProvider({ children }) {
  const [slotEl, setSlotEl] = useState(null)
  return (
    <TopbarSlotContext.Provider value={{ slotEl, setSlotEl }}>
      {children}
    </TopbarSlotContext.Provider>
  )
}

export function useTopbarSlot() {
  return useContext(TopbarSlotContext)
}
