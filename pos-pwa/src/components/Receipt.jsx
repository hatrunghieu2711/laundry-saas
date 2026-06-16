import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import BillContent from './Bill'
import { DEFAULT_RECEIPT, getReceiptConfig } from '../lib/receipt'

// Phiếu in khổ giấy nhiệt 80mm. Render qua portal ra <body> để khi @media print
// chỉ còn phiếu (ẩn .app-shell). Nội dung song ngữ lấy từ /settings/receipt.
// `config` (tùy chọn): caller có thể TRUYỀN SẴN receipt_config đã load (để auto-print
// dùng đúng mẫu tenant ngay từ render đầu — Stage 6.8.1). Không truyền → tự fetch.
export default function Receipt({ order, config: configProp }) {
  const [fetched, setFetched] = useState(null)

  useEffect(() => {
    if (configProp) return undefined // cha đã có config → khỏi fetch lại
    let alive = true
    getReceiptConfig().then((c) => {
      if (alive) setFetched(c)
    })
    return () => {
      alive = false
    }
  }, [configProp])

  if (!order) return null

  const config = configProp || fetched || DEFAULT_RECEIPT
  return createPortal(
    <div className="print-receipt">
      <BillContent config={config} order={order} />
    </div>,
    document.body,
  )
}
