import { useEffect, useState } from 'react'
import { createPortal } from 'react-dom'
import { QRCodeSVG } from 'qrcode.react'
import { api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'
import { PAYMENT_METHOD } from '../lib/orders'

// Phiếu in khổ giấy nhiệt 80mm (in được cả giấy thường A5/A6).
// Render qua portal ra <body> để khi @media print chỉ còn phiếu (ẩn .app-shell).
// Ẩn hoàn toàn trên màn hình (.print-receipt display:none), chỉ hiện khi in.
const OPEN_HOURS = '7:00 – 21:00 hằng ngày'

export default function Receipt({ order, paid = 0, method = null }) {
  const [branch, setBranch] = useState(null)

  useEffect(() => {
    if (!order?.branch_id) return undefined
    let alive = true
    api
      .get(`/branches/${order.branch_id}`)
      .then((b) => {
        if (alive) setBranch(b)
      })
      .catch(() => {})
    return () => {
      alive = false
    }
  }, [order?.branch_id])

  if (!order) return null

  const total = toNumber(order.total_amount)
  const paidSum = toNumber(paid)
  const remaining = total - paidSum
  const trackUrl = `${window.location.origin}/track/${order.order_code}`
  const methodLabel = method ? PAYMENT_METHOD[method] || method : null
  // Trạng thái thanh toán hiển thị rõ trên phiếu.
  const payState =
    total > 0 && paidSum >= total
      ? { label: methodLabel ? `ĐÃ THANH TOÁN (${methodLabel})` : 'ĐÃ THANH TOÁN', cls: 'rcp__paystatus--paid' }
      : paidSum > 0
        ? { label: 'THANH TOÁN MỘT PHẦN', cls: 'rcp__paystatus--part' }
        : { label: 'CHƯA THANH TOÁN', cls: 'rcp__paystatus--unpaid' }

  return createPortal(
    <div className="print-receipt">
      <div className="rcp">
        <div className="rcp__brand">Giặt Ủi 2H</div>
        <div className="rcp__branch">
          {branch ? (
            <>
              <div className="rcp__branch-name">
                {branch.code ? `${branch.code} · ` : ''}
                {branch.name}
              </div>
              {branch.address && <div>{branch.address}</div>}
              {branch.phone && <div>ĐT: {branch.phone}</div>}
            </>
          ) : (
            <div className="rcp__branch-name">Phiếu đơn hàng</div>
          )}
        </div>

        <div className="rcp__divider" />

        <div className="rcp__code-label">Mã đơn</div>
        <div className="rcp__code">{order.order_code}</div>

        {order.pickup_at && (
          <div className="rcp__pickup">Hẹn lấy: {formatPickupShort(order.pickup_at)}</div>
        )}

        <div className="rcp__qr">
          <QRCodeSVG value={trackUrl} size={132} level="M" />
          <div className="rcp__qr-cap">Quét để tra cứu đơn</div>
        </div>

        <div className="rcp__divider" />

        <div className="rcp__items">
          <div className="rcp__row rcp__row--head">
            <span>Dịch vụ</span>
            <span>Thành tiền</span>
          </div>
          {order.items.map((it) => (
            <div className="rcp__row" key={it.id}>
              <span className="rcp__item-name">
                {it.service_name}
                <small> × {toNumber(it.quantity)}</small>
              </span>
              <span>{formatVND(it.subtotal)}</span>
            </div>
          ))}
        </div>

        <div className="rcp__divider" />

        <div className="rcp__totals">
          <div className="rcp__row rcp__row--total">
            <span>Tổng tiền</span>
            <span>{formatVND(total)}</span>
          </div>
          <div className="rcp__row">
            <span>Đã thanh toán</span>
            <span>{formatVND(paidSum)}</span>
          </div>
          <div className="rcp__row rcp__row--due">
            <span>Còn lại</span>
            <span>{formatVND(remaining > 0 ? remaining : 0)}</span>
          </div>
        </div>

        <div className={`rcp__paystatus ${payState.cls}`}>{payState.label}</div>

        <div className="rcp__divider" />

        <div className="rcp__meta">
          <div>
            Lập lúc: {formatDateTime(order.created_at)}
            {order.created_by_name ? ` · ${order.created_by_name}` : ''}
          </div>
          {order.customer_name && <div>Khách: {order.customer_name}</div>}
        </div>

        <div className="rcp__foot">
          <div>Cảm ơn quý khách!</div>
          <div>Mở cửa {OPEN_HOURS}</div>
        </div>
      </div>
    </div>,
    document.body,
  )
}
