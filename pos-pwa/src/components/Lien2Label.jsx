import { createPortal } from 'react-dom'
import { formatLabelDateTime, formatLabelTime } from '../lib/datetime'
import { formatVND } from '../lib/format'

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
export function Lien2LabelBody({ order, seq = null, widthMm = null }) {
  const note = (order.notes || '').trim()
  const paid = order.payment_status === 'paid'
  // widthMm: override bề rộng .lbl (NATIVE chụp 68mm thay vì 76mm CSS để vừa vùng in 576 dots).
  // Default null → giữ CSS .lbl{width:76mm} (portal T1 / window.print KHÔNG đổi). Inline thắng class.
  const style = widthMm ? { width: `${widthMm}mm`, margin: '0 auto' } : undefined
  return (
    <div className="lbl" style={style}>
      {/* VẠCH MỐC chống cắt sát mã đơn (Stage 6.9.10) — thay spacer trắng (bị máy nhiệt
          trim hết). Vạch có MỰC (border-top đen) nên máy không trim qua; khe trắng giữa
          vạch và mã đơn được "kẹp" giữa 2 phần tử có mực → không bị trim. Đặt ĐẦU DOM: mã
          đơn là phần tử đầu → khi IN xoay 180° mã đơn rơi xuống ĐÁY giấy (mép cắt), vạch
          (đứng trước mã đơn) rơi xuống NGAY MÉP, khe ở giữa. Chỉ có mực+khe khi IN. */}
      <div className="lbl__cutline" aria-hidden="true" />
      <div className="lbl__head">
        <div className="lbl__code">{order.order_code}</div>
        {seq && <div className="lbl__num">{seq.n}/{seq.total}</div>}
      </div>
      <div className={`lbl__pay ${paid ? '' : 'lbl__pay--unpaid'}`}>{lien2PayText(order.payment_status)}</div>
      {/* Số tiền — CHỈ khi CHƯA thanh toán (paid thì đã thu, không cần) */}
      {!paid && <div className="lbl__amt">{formatVND(order.total_amount)}</div>}
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
// (OrderNew) lẫn in chủ động (Lien2PrintButton). Hiển thị bằng MOUNT/UNMOUNT (chỉ mount
// khi đang in nhãn) + @media print .print-lien2{display:block} (xem index.css).
// seq = {n,total} khi đánh số (1/N…N/N) | null. MỖI nhãn = 1 JOB riêng (1 window.print) →
// máy Sunmi cắt rời TỪNG nhãn (cắt ở CUỐI mỗi print job); hàng đợi tuần tự lo lặp N nhãn.
export function Lien2PrintLayer({ order, seq = null }) {
  if (!order) return null
  // ⭐ .print-lien2 > .lbl TRỰC TIẾP (bỏ wrapper .lbl-page) — parity với bill (.print-receipt >
  // .rcp). .lbl là con trực tiếp, dùng chung @page billpg.
  return createPortal(
    <div className="print-lien2">
      <Lien2LabelBody order={order} seq={seq} />
    </div>,
    document.body,
  )
}
