// Map tracking logs ([{status, at}]) → 4 bước timeline. Dùng chung tab Lịch sử
// (History.jsx) + bottom-sheet ☰ trên board (Board.jsx). Nguồn tracking = GET
// /orders/{id} (OrderDetailOut.tracking, Stage 6.41).
export const PAY_SUB = {
  paid: 'đã thu',
  debt: 'nợ',
  partial: 'thu 1 phần',
  unpaid: 'chưa thu',
  refunded: 'đã hoàn',
}

// washing|drying SỚM NHẤT = "Đang xử lý"; cancelled → bước cuối thành "Đã hủy" (đỏ).
// Bước chưa có mốc → at=undefined (UI hiện mờ "—").
export function buildTimeline(order) {
  const m = {}
  for (const e of order.tracking || []) {
    if (e.status === 'created' && !m.created) m.created = e.at
    if ((e.status === 'washing' || e.status === 'drying') && !m.proc) m.proc = e.at
    if (e.status === 'ready' && !m.ready) m.ready = e.at
    if (e.status === 'delivered' && !m.delivered) m.delivered = e.at
    if (e.status === 'cancelled') m.cancelled = e.at
  }
  const steps = [
    { label: 'Nhận đơn', at: m.created, sub: PAY_SUB[order.payment_status], subOk: order.payment_status === 'paid' },
    { label: 'Đang xử lý', at: m.proc },
    { label: 'Sẵn sàng', at: m.ready },
  ]
  steps.push(
    m.cancelled
      ? { label: 'Đã hủy', at: m.cancelled, danger: true }
      : { label: 'Đã giao', at: m.delivered },
  )
  return steps
}
