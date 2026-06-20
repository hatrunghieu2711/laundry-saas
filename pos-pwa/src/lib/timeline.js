// Map tracking logs ([{status, at}]) → 4 bước timeline. Dùng chung tab Lịch sử
// (History.jsx) + bottom-sheet ☰ trên board (Board.jsx). Nguồn tracking = GET
// /orders/{id} (OrderDetailOut.tracking, Stage 6.41). TIMELINE THUẦN trạng thái xử
// lý — KHÔNG kèm nhãn thanh toán (tình trạng thu đã có ở badge cạnh mã/tiền — 6.46).
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
    { label: 'Nhận đơn', at: m.created },
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
