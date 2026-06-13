import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import BillContent from './Bill'
import { DEFAULT_RECEIPT, getReceiptConfig } from '../lib/receipt'

// Phiếu in khổ giấy nhiệt 80mm. Render qua portal ra <body> để khi @media print
// chỉ còn phiếu (ẩn .app-shell). Nội dung + thứ tự khối lấy từ /settings/receipt.
export default function Receipt({ order, paid = 0, method = null }) {
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
      <BillContent config={config} order={order} paid={paid} method={method} />
    </div>,
    document.body,
  )
}
