// Nhãn tiếng Việt + map màu cho order/payment status. Dùng chung nhiều màn.

export const PAYMENT_STATUS = {
  unpaid: { label: 'Chưa thu', cls: 'ps--unpaid' },
  partial: { label: 'Thu một phần', cls: 'ps--partial' },
  paid: { label: 'Đã thu', cls: 'ps--paid' },
  debt: { label: 'Ghi nợ', cls: 'ps--debt' },
  refunded: { label: 'Đã hoàn', cls: 'ps--refunded' },
}

export const ORDER_STATUS = {
  created: 'Mới tạo',
  washing: 'Đang giặt',
  drying: 'Đang sấy',
  ready: 'Sẵn sàng',
  delivered: 'Đã giao',
  completed: 'Hoàn tất',
  cancelled: 'Đã hủy',
}

// Bước trạng thái tiến hợp lệ kế tiếp (khớp state machine backend).
export const NEXT_STATUS = {
  created: 'washing',
  washing: 'drying',
  drying: 'ready',
  ready: 'delivered',
  delivered: 'completed',
}

// Bước LÙI hợp lệ (Stage 3.9). delivered→ready chỉ khi unpaid (UI tự kiểm tra
// payment_status; backend enforce CANNOT_REVERT_PAID_DELIVERY).
export const PREV_STATUS = {
  washing: 'created',
  drying: 'washing',
  ready: 'drying',
  delivered: 'ready',
}

// Hủy được khi chưa giao (trước delivered).
export const CANCELLABLE = new Set(['created', 'washing', 'drying', 'ready'])

export const PAYMENT_METHOD = {
  cash: 'Tiền mặt',
  transfer: 'Chuyển khoản',
  qr: 'QR',
  cod: 'COD',
}

export const TXN_TYPE = {
  payment: 'Thu tiền',
  refund: 'Hoàn tiền',
  adjustment: 'Điều chỉnh',
  debt: 'Ghi nợ',
  resolve_debt: 'Trả nợ',
  cancel_paid: 'Hủy đã thu',
}

// Nhóm lọc theo order_status cho danh sách.
export const STATUS_FILTERS = [
  { key: 'active', label: 'Tất cả', statuses: ['created', 'washing', 'drying', 'ready', 'delivered'] },
  { key: 'processing', label: 'Đang xử lý', statuses: ['created', 'washing', 'drying'] },
  { key: 'ready', label: 'Sẵn sàng', statuses: ['ready'] },
  { key: 'delivered', label: 'Đã giao', statuses: ['delivered'] },
]
