import { QRCodeSVG } from 'qrcode.react'
import { formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'

// Phiếu (.rcp) THEO KHỐI (Stage 5.6). Đọc config.blocks → render đúng thứ tự hàng,
// 2 khối/hàng (chia đôi 80mm), bật/tắt, song ngữ (config.bilingual). Nhãn song ngữ
// cứng ở đây; nội dung khối text lấy từ block.content. Dùng chung in + preview.
const PAY_STATUS = {
  paid: ['ĐÃ THANH TOÁN', 'PAID'],
  partial: ['THANH TOÁN MỘT PHẦN', 'PARTIALLY PAID'],
  unpaid: ['CHƯA THANH TOÁN', 'UNPAID'],
  debt: ['GHI NỢ', 'ON CREDIT'],
  refunded: ['ĐÃ HOÀN TIỀN', 'REFUNDED'],
}

export default function BillContent({ config, order }) {
  if (!order) return null
  const bilingual = config?.bilingual !== false
  const blocks = Array.isArray(config?.blocks) ? config.blocks : []

  // Nhãn song ngữ: "vi / en" khi bật tiếng Anh, ngược lại chỉ "vi".
  const bi = (vi, en) => (bilingual && en ? `${vi} / ${en}` : vi)

  const grandTotal = toNumber(order.total_amount)
  const surcharge = toNumber(order.surcharge_amount)
  const discount = toNumber(order.discount_amount)
  const subtotal = order.subtotal != null ? toNumber(order.subtotal) : grandTotal

  const trackBase = import.meta.env.VITE_TRACK_BASE_URL || 'https://track.giatui2h.com'
  const trackUrl = `${trackBase}/track/${order.order_code}`

  // Một ô "nhãn: giá trị" (dùng cho giờ nhận/giao, số đơn — chạy được nửa hàng).
  const field = (vi, en, value) => (
    <div className="rcp__field">
      <b>{bi(vi, en)}:</b> {value || '—'}
    </div>
  )

  const th = (vi, en, cls) => (
    <th className={`rcp__th ${cls}`}>
      {vi}
      {bilingual && <span className="rcp__th-en">{en}</span>}
    </th>
  )

  // Render NỘI DUNG một khối theo type (trả null nếu không có gì để hiện).
  const renderBlock = (blk) => {
    const c = blk.content || {}
    switch (blk.type) {
      case 'logo':
        return (
          <div className="rcp__header">
            {config.logo_url ? (
              <img className="rcp__logo-img" src={config.logo_url} alt={c.shop_name || 'logo'} />
            ) : (
              c.logo_text && <div className="rcp__logo">{c.logo_text}</div>
            )}
            {c.shop_name && <div className="rcp__brand">{c.shop_name}</div>}
            <div className="rcp__title">{bilingual ? 'RECEIPT — BIÊN NHẬN' : 'BIÊN NHẬN'}</div>
          </div>
        )
      case 'customer_info':
        return (
          <div className="rcp__info">
            {field('Tên', 'Name', order.customer_name)}
            {field('ĐT', 'Tel', order.customer_phone)}
          </div>
        )
      case 'receiving_time':
        return field('Giờ nhận', 'Receiving', formatPickupShort(order.created_at))
      case 'delivery_time':
        return field('Giờ giao', 'Delivery', order.pickup_at ? formatPickupShort(order.pickup_at) : '')
      case 'items_table':
        return (
          <table className="rcp__table">
            <thead>
              <tr>
                {th('Dịch vụ', 'Service', 'rcp__th--name')}
                {th('SL', 'Qty', 'rcp__th--qty')}
                {th('Giá', 'Price', 'rcp__th--num')}
                {th('Tổng', 'Total', 'rcp__th--num')}
              </tr>
            </thead>
            <tbody>
              {order.items.map((it) => (
                <tr className="rcp__tr" key={it.id}>
                  <td className="rcp__td rcp__td--name">{it.service_name}</td>
                  <td className="rcp__td rcp__td--qty">{toNumber(it.quantity)}</td>
                  <td className="rcp__td rcp__td--num">{formatVND(it.unit_price)}</td>
                  <td className="rcp__td rcp__td--num">{formatVND(it.subtotal)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )
      case 'totals':
        return (
          <div className="rcp__totals">
            <div className="rcp__row"><span>{bi('Tạm tính', 'Subtotal')}</span><span>{formatVND(subtotal)}</span></div>
            {surcharge > 0 && (
              <div className="rcp__row">
                <span>{bi('Phụ thu', 'Surcharge')}{order.surcharge_reason ? ` (${order.surcharge_reason})` : ''}</span>
                <span>+{formatVND(surcharge)}</span>
              </div>
            )}
            {discount > 0 && (
              <div className="rcp__row">
                <span>{bi('Giảm', 'Discount')}{order.discount_reason ? ` (${order.discount_reason})` : ''}</span>
                <span>−{formatVND(discount)}</span>
              </div>
            )}
            <div className="rcp__row rcp__row--total"><span>{bi('TỔNG CỘNG', 'TOTAL')}</span><span>{formatVND(grandTotal)}</span></div>
          </div>
        )
      case 'surcharge_discount':
        if (surcharge <= 0 && discount <= 0) return null
        return (
          <div className="rcp__promo">
            {surcharge > 0 && (
              <div className="rcp__row"><span>{bi('Phụ thu', 'Surcharge')}{order.surcharge_reason ? ` (${order.surcharge_reason})` : ''}</span><span>+{formatVND(surcharge)}</span></div>
            )}
            {discount > 0 && (
              <div className="rcp__row"><span>{bi('Đã giảm', 'Discount')}{order.discount_reason ? ` (${order.discount_reason})` : ''}</span><span>−{formatVND(discount)}</span></div>
            )}
          </div>
        )
      case 'payment_status': {
        const [vi, en] = PAY_STATUS[order.payment_status] || PAY_STATUS.unpaid
        return <div className="rcp__paystatus">{bi(vi, en)}</div>
      }
      case 'note': {
        if (!c.vi && !c.en) return null
        return (
          <div className="rcp__note">
            <div className="rcp__note-label">{bi('Lưu ý', 'Important Note')}</div>
            {c.vi && <div className="rcp__note-vi">{c.vi}</div>}
            {bilingual && c.en && <div className="rcp__note-en">{c.en}</div>}
          </div>
        )
      }
      case 'qr_tracking':
        return (
          <div className="rcp__qr">
            <QRCodeSVG value={trackUrl} size={132} level="M" />
            <div className="rcp__qr-cap">{bi('Quét mã QR', 'Scan QR to track')}</div>
          </div>
        )
      case 'order_no':
        return <div className="rcp__no">{bi('Số', 'No')}: <b>{order.order_code}</b></div>
      case 'footer_contact': {
        const rows = [
          ['Hotline', 'Hotline', c.hotline],
          ['Web', 'Web', c.web],
          ['Địa chỉ', 'Add', c.address],
          ['Zalo / WA / Kakao', 'Zalo / WA / Kakao', c.zalo_wa_kakao],
          ['Giờ mở cửa', 'OPEN', c.open_hours],
        ].filter(([, , v]) => v && String(v).trim())
        if (!rows.length && !c.tagline) return null
        return (
          <div className="rcp__foot">
            {rows.map(([vi, en, value]) => (
              <div className="rcp__foot-row" key={vi}>
                <span className="rcp__foot-label">{bi(vi, en)}:</span> {value}
              </div>
            ))}
            {c.tagline && <div className="rcp__foot-tag">{c.tagline}</div>}
          </div>
        )
      }
      case 'custom_text':
        if (!c.vi && !c.en) return null
        return (
          <div className="rcp__custom">
            {c.vi && <div>{c.vi}</div>}
            {bilingual && c.en && <div className="rcp__custom-en">{c.en}</div>}
          </div>
        )
      default:
        return null
    }
  }

  // Gom khối ĐANG BẬT theo hàng; sắp hàng tăng dần, trong hàng: left → right.
  const enabled = blocks.filter((b) => b.enabled)
  const rowsMap = new Map()
  enabled.forEach((b) => {
    const r = b.row ?? 0
    if (!rowsMap.has(r)) rowsMap.set(r, [])
    rowsMap.get(r).push(b)
  })
  const rowKeys = [...rowsMap.keys()].sort((a, b) => a - b)
  const colOrder = { left: 0, full: 0, right: 1 }

  const nodes = []
  rowKeys.forEach((rk) => {
    const cells = rowsMap.get(rk).slice().sort((a, b) => (colOrder[a.col] ?? 0) - (colOrder[b.col] ?? 0))
    const rendered = cells
      .map((b) => ({ b, el: renderBlock(b) }))
      .filter((x) => x.el)
    if (!rendered.length) return
    if (nodes.length) nodes.push(<div className="rcp__divider" key={`d-${rk}`} />)
    if (rendered.length === 1) {
      nodes.push(<div key={`r-${rk}`}>{rendered[0].el}</div>)
    } else {
      nodes.push(
        <div className="rcp__brow" key={`r-${rk}`}>
          {rendered.map((x) => (
            <div className="rcp__bcell" key={x.b.id}>{x.el}</div>
          ))}
        </div>,
      )
    }
  })

  return <div className="rcp">{nodes}</div>
}
