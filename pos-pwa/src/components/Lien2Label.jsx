import { createPortal } from 'react-dom'
import { formatLabelDateTime, formatLabelTime } from '../lib/datetime'
import { formatVND } from '../lib/format'
import { DEFAULT_LIEN2 } from '../lib/receipt'

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
export function Lien2LabelBody({ order, seq = null, widthMm = null, cfg = null }) {
  const note = (order.notes || '').trim()
  const paid = order.payment_status === 'paid'
  // cfg = lien2_config (bật/tắt thành phần + cỡ mã đơn). Null → DEFAULT_LIEN2 (mọi thứ bật, large →
  // y hành vi cũ). Mã đơn + số nhãn LUÔN hiện (không trong config).
  const c = cfg || DEFAULT_LIEN2
  const codeCls = c.code_size === 'small' ? 'lbl__code--small' : c.code_size === 'normal' ? 'lbl__code--normal' : ''
  // Số nhãn (1/N) đổi cỡ CÙNG mã đơn (mục 3) → cùng tier code_size, cân đối trên 1 hàng.
  const numCls = c.code_size === 'small' ? 'lbl__num--small' : c.code_size === 'normal' ? 'lbl__num--normal' : ''
  const showName = c.show_customer_name
  const showRecv = c.show_recv_time
  const showPickup = c.show_pickup_time
  const showAmount = c.show_amount && !paid // số tiền chỉ khi chưa TT (giữ logic cũ)
  const showPay = c.show_payment_status
  const showNote = c.show_note && !!note
  const footerText = (c.footer_text || '').trim()
  const showFooter = c.show_footer_text === true && !!footerText // dòng thông tin thêm cuối nhãn (Phần B)
  // 2 DÒNG INFO (Phần A): dòng 1 = tên + tiền; dòng 2 = giờ nhận + giờ giao. Mỗi dòng hiện nếu còn
  // ≥1 thành phần bật (tôn trọng show_*); dòng vẫn cân khi chỉ còn 1 thứ.
  const showRow1 = showName || showAmount
  const showRow2 = showRecv || showPickup
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
        <div className={`lbl__code ${codeCls}`}>{order.order_code}</div>
        {seq && <div className={`lbl__num ${numCls}`}>{seq.n}/{seq.total}</div>}
      </div>
      {showPay && <div className={`lbl__pay ${paid ? '' : 'lbl__pay--unpaid'}`}>{lien2PayText(order.payment_status)}</div>}
      {/* DÒNG 1 (Phần A): tên (trái, normal, co/ellipsis) + SỐ TIỀN (phải, đậm, chỉ chưa-TT). Bỏ
          label "Name:". Khi đã-TT → chỉ tên (canh trái). Tôn trọng show_*. */}
      {showRow1 && (
        <div className="lbl__row">
          {showName && <span className="lbl__row-name">{order.customer_name || 'Khách vãng lai'}</span>}
          {showAmount && <span className="lbl__row-amt">{formatVND(order.total_amount)}</span>}
        </div>
      )}
      {/* DÒNG 2 (Phần A): giờ nhận (trái, nhỏ, normal) + giờ giao (phải, LỚN + ĐẬM = quan trọng nhất
          khi trả khách). Bỏ label "Time:". Tôn trọng show_*. */}
      {showRow2 && (
        <div className="lbl__timeRow">
          {showRecv && <span className="lbl__recv">{formatLabelTime(order.created_at)}</span>}
          {showPickup && <span className="lbl__pickup">{formatLabelDateTime(order.pickup_at)}</span>}
        </div>
      )}
      {showNote && <div className="lbl__note">Ghi chú: {note}</div>}
      {/* Dòng thông tin thêm (Phần B) — tenant tự nhập (SĐT/địa chỉ…), cuối nhãn, mặc định TẮT. */}
      {showFooter && <div className="lbl__footer">{footerText}</div>}
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
export function Lien2PrintLayer({ order, seq = null, cfg = null }) {
  if (!order) return null
  // ⭐ .print-lien2 > .lbl TRỰC TIẾP (bỏ wrapper .lbl-page) — parity với bill (.print-receipt >
  // .rcp). .lbl là con trực tiếp, dùng chung @page billpg. cfg = lien2_config (bật/tắt + cỡ mã).
  return createPortal(
    <div className="print-lien2">
      <Lien2LabelBody order={order} seq={seq} cfg={cfg} />
    </div>,
    document.body,
  )
}
