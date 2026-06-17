import { createPortal } from 'react-dom'
import { formatLabelDateTime, formatLabelTime } from '../lib/datetime'

// NHÃN LIÊN 2 (dán túi đồ — nội bộ, Stage 6.9). Mẫu CỐ ĐỊNH mọi tenant (không
// builder): khổ 80mm in nhiệt, monospace, chữ to, KHÔNG bảng món/QR/logo.
// Ngày in CHÍNH XÁC "DD/MM HH:MM" (không "Hôm nay/Ngày mai").
//
// Trạng thái thanh toán: paid → "Đã thanh toán / Paid"; còn lại (unpaid/partial/
// debt/refunded) → "Chưa thanh toán / Unpaid". (Nhãn túi chỉ cần phân biệt đã thu
// đủ hay chưa; nợ/thu một phần đều coi là CHƯA thanh toán.)
export const lien2PayText = (status) =>
  status === 'paid' ? 'Đã thanh toán / Paid' : 'Chưa thanh toán / Unpaid'

// Thân nhãn (KHÔNG portal) — tách để in nhiều nhãn + screenshot. seq = {n,total}
// khi đánh số; null = không số (ẩn ô số túi, mã đơn chiếm full ngang).
export function Lien2LabelBody({ order, seq = null }) {
  const note = (order.notes || '').trim()
  return (
    <div className="lbl">
      <div className="lbl__head">
        <div className="lbl__code">{order.order_code}</div>
        {seq && <div className="lbl__num">{seq.n}/{seq.total}</div>}
      </div>
      <div className="lbl__pay">{lien2PayText(order.payment_status)}</div>
      <div className="lbl__info">
        {/* Name (trái) + giờ nhận HH:MM (phải) cùng 1 dòng — Stage 6.9.1 */}
        <div className="lbl__nameRow">
          <span>Name: <b>{order.customer_name || 'Khách vãng lai'}</b></span>
          <span className="lbl__recv">{formatLabelTime(order.created_at)}</span>
        </div>
        {/* Giờ giao: dòng riêng, nổi bật, GIỮ ngày + giờ (giao có thể qua ngày) */}
        <div className="lbl__deliv">
          <span className="lbl__k">Giao/Delivery time:</span> <span className="lbl__v">{formatLabelDateTime(order.pickup_at)}</span>
        </div>
      </div>
      {note && <div className="lbl__note">Ghi chú: {note}</div>}
      <div className="lbl__blank" />
    </div>
  )
}

// Nhãn KÈM BILL (chế độ a): 1 nhãn KHÔNG SỐ, dùng class .print-receipt nên in
// chung 1 lần với bill (page-break tự cắt giữa bill và nhãn). Render cạnh <Receipt>.
export function Lien2BillLabel({ order }) {
  if (!order) return null
  return createPortal(
    <div className="print-receipt print-receipt--label">
      <Lien2LabelBody order={order} seq={null} />
    </div>,
    document.body,
  )
}
