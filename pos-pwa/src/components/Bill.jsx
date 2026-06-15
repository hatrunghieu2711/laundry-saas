import { QRCodeSVG } from 'qrcode.react'
import { formatDateTime, formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'
import { PAYMENT_METHOD } from '../lib/orders'

// Nội dung phiếu (.rcp) render theo cấu hình blocks {key,enabled,order}.
// Dùng chung cho in (Receipt.jsx, qua portal) và preview (màn cấu hình).
export default function BillContent({ config, order, paid = 0, method = null }) {
  if (!order) return null
  const total = toNumber(order.total_amount)
  const paidSum = toNumber(paid)
  const remaining = total - paidSum
  // QR trỏ về trang tracking công khai (subdomain riêng), KHÔNG phải origin POS.
  // Cấu hình qua VITE_TRACK_BASE_URL khi build; mặc định track.giatui2h.com.
  const trackBase = import.meta.env.VITE_TRACK_BASE_URL || 'https://track.giatui2h.com'
  const trackUrl = `${trackBase}/track/${order.order_code}`
  const methodLabel = method ? PAYMENT_METHOD[method] || method : null
  const payState =
    total > 0 && paidSum >= total
      ? { label: methodLabel ? `ĐÃ THANH TOÁN (${methodLabel})` : 'ĐÃ THANH TOÁN', cls: 'rcp__paystatus--paid' }
      : paidSum > 0
        ? { label: 'THANH TOÁN MỘT PHẦN', cls: 'rcp__paystatus--part' }
        : { label: 'CHƯA THANH TOÁN', cls: 'rcp__paystatus--unpaid' }

  const render = {
    header: () => (
      <div className="rcp__header">
        {config.logo_text && <div className="rcp__logo">{config.logo_text}</div>}
        <div className="rcp__brand">{config.shop_name || 'Phiếu đơn hàng'}</div>
        {config.address && <div className="rcp__branch">{config.address}</div>}
        {config.phone && <div className="rcp__branch">ĐT: {config.phone}</div>}
      </div>
    ),
    order_code: () => (
      <div>
        <div className="rcp__code-label">Mã đơn</div>
        <div className="rcp__code">{order.order_code}</div>
      </div>
    ),
    pickup_time: () =>
      order.pickup_at ? (
        <div className="rcp__pickup">Hẹn lấy: {formatPickupShort(order.pickup_at)}</div>
      ) : null,
    qr_tracking: () => (
      <div className="rcp__qr">
        <QRCodeSVG value={trackUrl} size={132} level="M" />
        <div className="rcp__qr-cap">Quét để tra cứu đơn</div>
      </div>
    ),
    items: () => (
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
    ),
    totals: () => (
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
    ),
    payment_status: () => <div className={`rcp__paystatus ${payState.cls}`}>{payState.label}</div>,
    meta: () => (
      <div className="rcp__meta">
        <div>
          Lập lúc: {formatDateTime(order.created_at)}
          {order.created_by_name ? ` · ${order.created_by_name}` : ''}
        </div>
        {order.customer_name && <div>Khách: {order.customer_name}</div>}
      </div>
    ),
    footer: () => (
      <div className="rcp__foot">
        {config.footer_text && <div>{config.footer_text}</div>}
        {config.open_hours && <div>Mở cửa {config.open_hours}</div>}
      </div>
    ),
  }

  const blocks = [...(config.blocks || [])]
    .sort((a, b) => (a.order ?? 0) - (b.order ?? 0))
    .filter((b) => b.enabled)

  const nodes = []
  blocks.forEach((b, i) => {
    const el = render[b.key]?.()
    if (!el) return
    if (nodes.length) nodes.push(<div className="rcp__divider" key={`d${i}`} />)
    nodes.push(<div key={b.key}>{el}</div>)
  })

  return <div className="rcp">{nodes}</div>
}
