import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import BillContent from './Bill'
import { DEFAULT_RECEIPT, getReceiptConfig } from '../lib/receipt'

// Phiếu in khổ giấy nhiệt 80mm. Render qua portal ra <body> để khi @media print
// chỉ còn phiếu (ẩn .app-shell). Nội dung song ngữ lấy từ /settings/receipt.
// (paid/method không còn hiển thị trên mẫu 2H — giữ prop để caller cũ khỏi vỡ.)
export default function Receipt({ order }) {
  const [config, setConfig] = useState(DEFAULT_RECEIPT)

  useEffect(() => {
    let alive = true
    getReceiptConfig().then((c) => {
      if (alive) setConfig(c)
    })
    return () => {
      alive = false
    }
  }, [])

  if (!order) return null

  return createPortal(
    <div className="print-receipt">
      <BillContent config={config} order={order} />
    </div>,
    document.body,
  )
}
