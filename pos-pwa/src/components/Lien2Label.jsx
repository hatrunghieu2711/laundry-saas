import { createPortal } from 'react-dom'
import { formatLabelDateTime, formatLabelTime } from '../lib/datetime'

// NHÃN LIÊN 2 (dán túi đồ — nội bộ, Stage 6.9). Mẫu CỐ ĐỊNH mọi tenant (không
// builder): khổ 80mm in nhiệt, monospace, chữ to, KHÔNG bảng món/QR/logo.
// Ngày in CHÍNH XÁC "DD/MM HH:MM" (không "Hôm nay/Ngày mai").
//
// Trạng thái thanh toán (IN HOA): paid → "ĐÃ THANH TOÁN / PAID"; còn lại (unpaid/
// partial/debt/refunded) → "CHƯA THANH TOÁN / UNPAID". Nhãn túi chỉ cần phân biệt đã
// thu đủ hay chưa; nợ/thu một phần đều coi là CHƯA thanh toán.
export const lien2PayText = (status) =>
  status === 'paid' ? 'ĐÃ THANH TOÁN / PAID' : 'CHƯA THANH TOÁN / UNPAID'

// Thân nhãn (KHÔNG portal) — tách để in nhiều nhãn + screenshot. seq = {n,total}
// khi đánh số; null = không số (ẩn ô số túi, mã đơn chiếm full ngang). Style v5
// (Stage 6.9.6): đậm hơn, to hơn; UNPAID có khung (cảnh giác khi giao), PAID không.
export function Lien2LabelBody({ order, seq = null }) {
  const note = (order.notes || '').trim()
  const paid = order.payment_status === 'paid'
  return (
    <div className="lbl">
      {/* SPACER chống cắt sát mã đơn (Stage 6.9.9). Là NỘI DUNG THẬT (div có chiều cao
          khi in), KHÁC padding — máy in feed hết vùng này rồi mới tới mã đơn. Đặt ĐẦU DOM:
          mã đơn là phần tử đầu → khi IN xoay 180° mã đơn rơi xuống ĐÁY giấy (mép máy cắt),
          spacer (đứng trước mã đơn trong DOM) rơi xuống DƯỚI mã đơn = giữa mã đơn và mép cắt.
          Chỉ có chiều cao khi IN (xem @media print) — không ảnh hưởng preview màn hình. */}
      <div className="lbl__spacer" aria-hidden="true" />
      <div className="lbl__head">
        <div className="lbl__code">{order.order_code}</div>
        {seq && <div className="lbl__num">{seq.n}/{seq.total}</div>}
      </div>
      <div className={`lbl__pay ${paid ? '' : 'lbl__pay--unpaid'}`}>{lien2PayText(order.payment_status)}</div>
      <div className="lbl__info">
        {/* Name (trái) + giờ nhận HH:MM (phải) cùng 1 dòng */}
        <div className="lbl__nameRow">
          <span>Name: {order.customer_name || 'Khách vãng lai'}</span>
          <span className="lbl__recv">{formatLabelTime(order.created_at)}</span>
        </div>
        {/* Giờ giao: "Time: DD/MM HH:MM" — TO + ĐẬM nhất (quan trọng khi giao) */}
        <div className="lbl__time">Time: {formatLabelDateTime(order.pickup_at)}</div>
      </div>
      {note && <div className="lbl__note">Ghi chú: {note}</div>}
      {/* Vùng viết tay = khoảng trắng padding-bottom của .lbl (v6) — bỏ dòng dấu chấm. */}
    </div>
  )
}

// Lớp in nhãn liên 2 (Stage 6.9.4) — portal ra <body> (NGOÀI #root, vì #root bị
// display:none khi in). Render 1 nhãn ĐANG in của hàng đợi. Dùng cho cả auto-print
// (OrderNew) lẫn in chủ động (Lien2PrintButton). Body class print-job-lien2 quyết
// định hiển thị (xem index.css @media print).
export function Lien2PrintLayer({ order, seq = null }) {
  if (!order) return null
  return createPortal(
    <div className="print-lien2">
      <div className="lbl-page"><Lien2LabelBody order={order} seq={seq} /></div>
    </div>,
    document.body,
  )
}
