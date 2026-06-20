import { createPortal } from 'react-dom'
import { formatDateTime, formatVND, toNumber } from '../lib/format'

// Phiếu giao ca in nhiệt 80mm (Stage 6.2). Dùng lại primitives .rcp (print portal
// + @media print ẩn app, hiện .print-receipt). kind: 'handover' | 'report'.
// - handover: Biên nhận nộp tiền (chỉ in khi handover>0) — kẹp cọc cho chủ.
// - report: Biên bản giao ca — đối soát tiền + rút nộp chủ + để lại ca sau.
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
  // Chênh lệch ca (để chủ nhận tiền thấy ngay) — CHỈ in dòng nào ≠0; ca khớp → không in gì.
  const openingDiff = toNumber(shift.opening_diff)
  const cashDiff = toNumber(shift.cash_difference)
  const hasDiff = openingDiff !== 0 || cashDiff !== 0
  return (
    <div className="rcp sslip">
      <div className="rcp__title sslip__title">BIÊN NHẬN NỘP TIỀN</div>
      {branchName && <div className="sslip__sub">{branchName}</div>}
      <div className="rcp__divider" />
      <Row label="Ca" value={sid(shift.id)} />
      <Row label="Mở ca" value={formatDateTime(shift.opened_at)} />
      <Row label="Đóng ca" value={formatDateTime(shift.closed_at)} />
      <Row label="Nhân viên nộp" value={shift.closed_by_name || '—'} />
      <div className="rcp__divider" />
      <Row label="SỐ TIỀN NỘP" value={formatVND(shift.handover_to_owner)} total />
      <div className="rcp__divider" />
      {hasDiff && (
        <>
          {openingDiff !== 0 && (
            <>
              <Row label="Chênh lệch đầu ca" value={`${openingDiff > 0 ? '+' : ''}${formatVND(shift.opening_diff)}`} />
              {shift.opening_diff_reason && (
                <div className="sslip__reason">Lý do: {shift.opening_diff_reason}</div>
              )}
            </>
          )}
          {cashDiff !== 0 && (
            <>
              <Row label="Chênh lệch cuối ca" value={`${cashDiff > 0 ? '+' : ''}${formatVND(shift.cash_difference)}`} />
              {shift.cash_diff_reason && (
                <div className="sslip__reason">Lý do: {shift.cash_diff_reason}</div>
              )}
            </>
          )}
          <div className="rcp__divider" />
        </>
      )}
    </div>
  )
}

function HandoverReport({ shift, branchName }) {
  const transfer = toNumber(shift.total_transfer) + toNumber(shift.total_qr)
  return (
    <div className="rcp sslip">
      <div className="rcp__title sslip__title">BIÊN BẢN GIAO CA</div>
      {branchName && <div className="sslip__sub">{branchName}</div>}
      <div className="rcp__field" style={{ textAlign: 'center' }}>Ca: {sid(shift.id)}</div>
      <div className="rcp__divider" />
      <Row label="Mở ca" value={formatDateTime(shift.opened_at)} />
      <Row label="Đóng ca" value={formatDateTime(shift.closed_at)} />
      <div className="rcp__divider" />

      <div className="sslip__h">Đối soát tiền mặt</div>
      <Row label="Đầu ca" value={formatVND(shift.opening_cash)} />
      <Row label="Tiền mặt thu" value={formatVND(shift.total_cash)} />
      {toNumber(shift.total_income) > 0 && <Row label="+ Thu sổ quỹ" value={formatVND(shift.total_income)} />}
      {toNumber(shift.total_expense) > 0 && <Row label="− Chi sổ quỹ" value={formatVND(shift.total_expense)} />}
      <Row label="Phải có" value={formatVND(shift.closing_cash_expected)} />
      <Row label="Đếm thực tế" value={formatVND(shift.closing_cash_actual)} />
      <Row label="Chênh lệch" value={formatVND(shift.cash_difference)} total />
      {toNumber(shift.cash_difference) !== 0 && shift.cash_diff_reason && (
        <div className="sslip__reason">Lý do lệch cuối ca: {shift.cash_diff_reason}</div>
      )}
      {shift.opening_diff != null && toNumber(shift.opening_diff) !== 0 && (
        <>
          <Row
            label="Lệch đầu ca"
            value={`${toNumber(shift.opening_diff) > 0 ? '+' : ''}${formatVND(shift.opening_diff)}`}
          />
          {shift.opening_diff_reason && (
            <div className="sslip__reason">Lý do lệch đầu ca: {shift.opening_diff_reason}</div>
          )}
        </>
      )}

      <div className="rcp__divider" />
      <Row label="Rút nộp chủ" value={formatVND(shift.handover_to_owner)} />
      <Row label="Tiền để lại ca sau" value={formatVND(shift.cash_left_for_next)} total />

      <div className="rcp__divider" />
      <Row label="Chuyển khoản / QR" value={formatVND(transfer)} />
      <div className="sslip__note">(đối chiếu sao kê ngân hàng)</div>
    </div>
  )
}

// Thân phiếu (không portal) — tách để preview/screenshot render được (SSR không có portal).
export function ShiftSlipBody({ kind, shift, branchName }) {
  if (!kind || !shift) return null
  return kind === 'handover'
    ? <HandoverReceipt shift={shift} branchName={branchName} />
    : <HandoverReport shift={shift} branchName={branchName} />
}

export default function ShiftSlip(props) {
  const body = ShiftSlipBody(props)
  if (!body) return null
  return createPortal(<div className="print-receipt">{body}</div>, document.body)
}
