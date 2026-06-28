import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import BillContent from './Bill'
import { DEFAULT_RECEIPT, getReceiptConfig } from '../lib/receipt'
import { dbgLog, usePrintMode } from '../lib/printQueue' // dbgLog ⚠️ DEBUG TẠM

// Phiếu in khổ giấy nhiệt 80mm. Render qua portal ra <body> để khi @media print
// chỉ còn phiếu (ẩn .app-shell). Nội dung song ngữ lấy từ /settings/receipt.
// `config` (tùy chọn): caller có thể TRUYỀN SẴN receipt_config đã load (để auto-print
// dùng đúng mẫu tenant ngay từ render đầu — Stage 6.8.1). Không truyền → tự fetch.
export default function Receipt({ order, config: configProp }) {
  const [fetched, setFetched] = useState(null)
  const printMode = usePrintMode() // 'lien2' → UNMOUNT bill (fix T2: không phụ thuộc body class)

  // ⚠️ DEBUG TẠM — log mỗi khi printMode đổi: Receipt CÓ return null (unmount bill) khi 'lien2'?
  useEffect(() => {
    dbgLog(`Receipt mode=${printMode} -> ${printMode === 'lien2' ? 'RETURN NULL (unmount bill)' : 'render bill'}`)
  }, [printMode])

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
  // ⚠️ Đang in LIÊN 2 → BỎ bill khỏi DOM (T2 không áp body class trong print → display:none
  // vô hiệu; phải unmount). Khi đó chỉ còn .print-lien2 → T2 in đúng nhãn. mode null/'bill'
  // → bill mount bình thường (in bill mọi đường: OrderNew/OrderDetail/Board/OrderPay/History).
  if (printMode === 'lien2') return null

  const config = configProp || fetched || DEFAULT_RECEIPT
  return createPortal(
    <div className="print-receipt">
      <BillContent config={config} order={order} />
    </div>,
    document.body,
  )
}
