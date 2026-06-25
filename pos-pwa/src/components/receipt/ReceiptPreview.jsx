import { useMemo } from 'react'
import BillContent from '../Bill'

// Demo cho preview builder: KHÔNG đặt surcharge_reason/discount_reason để preview
// giữ nhãn chung "Phụ thu"/"Giảm giá" (tên chiến dịch chỉ hiện ở bill IN THẬT).
const SAMPLE_ORDER = {
  order_code: 'B1-00042',
  subtotal: 185000, surcharge_amount: 18500, discount_amount: 15000,
  total_amount: 188500, payment_status: 'paid',
  pickup_at: '2026-06-14T03:30:00Z', created_at: '2026-06-13T09:15:00Z',
  customer_name: 'Chị Lan', customer_phone: '0905 123 456',
  // branch_id gán động ở preview (= CN đang xem) → khu "Liên hệ theo CN" hiện đúng.
  items: [
    { id: 1, service_name: 'Giặt sấy (≤3kg)', quantity: 1, unit_price: 60000, subtotal: 60000 },
    { id: 2, service_name: 'Áo Vest', quantity: 2, unit_price: 60000, subtotal: 120000 },
    { id: 3, service_name: 'Giặt thường', quantity: 1, unit_price: 5000, subtotal: 5000 },
  ],
}

// Cột xem trước (khổ 80mm) — render BillContent từ previewConfig + đơn GIẢ. branches/previewCn
// optional (admin mẫu chuẩn: không có CN → bỏ selector). slug optional cho QR (admin truyền
// placeholder; tenant truyền tenant_slug). (Stage refactor editor: tách từ ReceiptSettings.)
export default function ReceiptPreview({ config, branches = [], previewCn, onPreviewCn, slug }) {
  const previewOrder = useMemo(() => ({ ...SAMPLE_ORDER, branch_id: previewCn }), [previewCn])
  return (
    <div className="rcfg__preview">
      <div className="rcfg__preview-label">Xem trước (khổ 80mm)</div>
      {branches.length > 0 && (
        <label className="field rcfg__preview-cn">
          <span>Xem theo chi nhánh</span>
          <select className="input" value={previewCn || ''} onChange={(e) => onPreviewCn(e.target.value)}>
            {branches.map((b) => (
              <option key={b.id} value={b.id}>{b.order_prefix} · {b.name}</option>
            ))}
          </select>
        </label>
      )}
      <div className="rcp-preview">
        <BillContent config={config} order={previewOrder} slug={slug} />
      </div>
    </div>
  )
}
