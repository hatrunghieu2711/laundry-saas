import { createPortal } from 'react-dom'
import { formatDateTime, formatVND, toNumber } from '../lib/format'

// Phiếu giao ca in nhiệt 80mm (Stage 6.2). Dùng lại primitives .rcp (print portal
// + @media print ẩn app, hiện .print-receipt). kind: 'handover' | 'report'.
// - handover: Biên nhận nộp tiền chủ (chỉ in khi handover>0) — kẹp cọc cho chủ.
// - report: Biên bản giao ca — đối soát tiền + rút nộp chủ + tình hình bàn giao.
const sid = (id) => (id ? String(id).slice(0, 8).toUpperCase() : '—')

function Row({ label, value, total }) {
  return (
    <div className={`rcp__row ${total ? 'rcp__row--total' : ''}`}>
      <span className="rcp__row-lbl">{label}</span>
      <span className="rcp__row-amt">{value}</span>
    </div>
  )
}

function HandoverReceipt({ shift, branchName }) {
  return (
    <div className="rcp">
      <div className="rcp__title">BIÊN NHẬN NỘP TIỀN CHỦ</div>
      {branchName && <div className="sslip__sub">{branchName}</div>}
      <div className="rcp__divider" />
      <div className="rcp__field"><b>Ca:</b> {sid(shift.id)}</div>
      <div className="rcp__field"><b>Mở ca:</b> {formatDateTime(shift.opened_at)}</div>
      <div className="rcp__field"><b>Đóng ca:</b> {formatDateTime(shift.closed_at)}</div>
      <div className="rcp__field"><b>Nhân viên nộp:</b> {shift.closed_by_name || '—'}</div>
      <div className="rcp__divider" />
      <Row label="SỐ TIỀN NỘP CHỦ" value={formatVND(shift.handover_to_owner)} total />
      <div className="rcp__divider" />
      <div className="sslip__signs">
        <div>Người nộp<br />______________</div>
        <div>Chủ nhận<br />______________</div>
      </div>
    </div>
  )
}

function HandoverReport({ shift, branchName, board }) {
  const transfer = toNumber(shift.total_transfer) + toNumber(shift.total_qr)
  return (
    <div className="rcp">
      <div className="rcp__title">BIÊN BẢN GIAO CA</div>
      {branchName && <div className="sslip__sub">{branchName}</div>}
      <div className="rcp__field" style={{ textAlign: 'center' }}>Ca: {sid(shift.id)}</div>
      <div className="rcp__divider" />
      <div className="rcp__field"><b>Mở ca:</b> {formatDateTime(shift.opened_at)}</div>
      <div className="rcp__field"><b>Đóng ca:</b> {formatDateTime(shift.closed_at)}</div>
      <div className="rcp__divider" />

      <div className="sslip__h">Đối soát tiền mặt</div>
      <Row label="Đầu ca" value={formatVND(shift.opening_cash)} />
      <Row label="Tiền mặt thu" value={formatVND(shift.total_cash)} />
      {toNumber(shift.total_income) > 0 && <Row label="+ Thu sổ quỹ" value={formatVND(shift.total_income)} />}
      {toNumber(shift.total_expense) > 0 && <Row label="− Chi sổ quỹ" value={formatVND(shift.total_expense)} />}
      <Row label="Phải có" value={formatVND(shift.closing_cash_expected)} />
      <Row label="Đếm thực tế" value={formatVND(shift.closing_cash_actual)} />
      <Row label="Chênh lệch" value={formatVND(shift.cash_difference)} total />

      <div className="rcp__divider" />
      <Row label="Rút nộp chủ" value={formatVND(shift.handover_to_owner)} />
      <Row label="Tiền để lại ca sau" value={formatVND(shift.cash_left_for_next)} total />

      <div className="rcp__divider" />
      <Row label="Chuyển khoản / QR" value={formatVND(transfer)} />
      <div className="sslip__note">(đối chiếu sao kê ngân hàng)</div>

      {board && (
        <>
          <div className="rcp__divider" />
          <div className="sslip__h">Tình hình bàn giao</div>
          <Row label="Đơn đang xử lý (chưa giao)" value={board.processing} />
          <Row label="Đơn trễ hẹn" value={board.overdue} />
          <Row label="Đơn còn nợ tiền" value={board.owing} />
        </>
      )}

      <div className="rcp__divider" />
      <div className="rcp__field"><b>Người giao:</b> {shift.closed_by_name || '—'}</div>
      <div className="sslip__signs">
        <div>Người nhận<br />______________</div>
        <div>Ghi chú<br />______________</div>
      </div>
    </div>
  )
}

// Thân phiếu (không portal) — tách để preview/screenshot render được (SSR không có portal).
export function ShiftSlipBody({ kind, shift, branchName, board }) {
  if (!kind || !shift) return null
  return kind === 'handover'
    ? <HandoverReceipt shift={shift} branchName={branchName} />
    : <HandoverReport shift={shift} branchName={branchName} board={board} />
}

export default function ShiftSlip(props) {
  const body = ShiftSlipBody(props)
  if (!body) return null
  return createPortal(<div className="print-receipt">{body}</div>, document.body)
}
