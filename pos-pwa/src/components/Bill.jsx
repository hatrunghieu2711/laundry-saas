import { QRCodeSVG } from 'qrcode.react'
import { formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'

// Phiếu (.rcp) THEO KHỐI (Stage 5.6) + nhãn sửa được & định dạng theo khối (5.7).
// - Nhãn cố định mỗi khối lưu ở content (`<key>_vi`/`<key>_en`); thiếu → fallback
//   về text cứng mặc định (LDEF). Giá trị động (tên khách, tiền, mã đơn…) tự điền.
// - Mỗi khối có bold / align / size + 2 khối/hàng (ghép tự do). Dùng chung in+preview.
const PAY_STATUS = {
  paid: ['ĐÃ THANH TOÁN', 'PAID'], partial: ['THANH TOÁN MỘT PHẦN', 'PARTIALLY PAID'],
  unpaid: ['CHƯA THANH TOÁN', 'UNPAID'], debt: ['GHI NỢ', 'ON CREDIT'],
  refunded: ['ĐÃ HOÀN TIỀN', 'REFUNDED'],
}
// Nhãn mặc định (= text cứng) cho từng khối — fallback khi owner chưa sửa.
const LDEF = {
  logo: { title: ['BIÊN NHẬN', 'RECEIPT'] },
  customer_info: { name: ['Tên', 'Name'], tel: ['ĐT', 'Tel'] },
  receiving_time: { label: ['Giờ nhận', 'Receiving'] },
  delivery_time: { label: ['Giờ giao', 'Delivery'] },
  items_table: { svc: ['Dịch vụ', 'Service'], qty: ['SL', 'Qty'], price: ['Giá', 'Price'], total: ['Tổng', 'Total'] },
  totals: { subtotal: ['Tạm tính', 'Subtotal'], surcharge: ['Phụ thu', 'Surcharge'], discount: ['Giảm', 'Discount'], total: ['TỔNG CỘNG', 'TOTAL'] },
  surcharge_discount: { sur: ['Phụ thu', 'Surcharge'], dis: ['Đã giảm', 'Discount'] },
  note: { label: ['Lưu ý', 'Important Note'] },
  qr_tracking: { cap: ['Quét mã QR', 'Scan QR to track'] },
  order_no: { label: ['Số', 'No'] },
  footer_contact: {
    lbl_hotline: ['Hotline', 'Hotline'], lbl_web: ['Web', 'Web'], lbl_address: ['Địa chỉ', 'Add'],
    lbl_zalo: ['Zalo / WA / Kakao', 'Zalo / WA / Kakao'], lbl_open: ['Giờ mở cửa', 'OPEN'],
  },
}
const DEF_ALIGN = {
  logo: 'center', qr_tracking: 'center', order_no: 'center',
  payment_status: 'center', footer_contact: 'center', custom_text: 'center',
}

export default function BillContent({ config, order }) {
  if (!order) return null
  const bilingual = config?.bilingual !== false
  const blocks = Array.isArray(config?.blocks) ? config.blocks : []

  const grandTotal = toNumber(order.total_amount)
  const surcharge = toNumber(order.surcharge_amount)
  const discount = toNumber(order.discount_amount)
  const subtotal = order.subtotal != null ? toNumber(order.subtotal) : grandTotal
  const trackBase = import.meta.env.VITE_TRACK_BASE_URL || 'https://track.giatui2h.com'
  const trackUrl = `${trackBase}/track/${order.order_code}`

  // Nhãn song ngữ của khối: content[key_vi/_en] || mặc định LDEF.
  const lbl = (type, c, key) => {
    const d = LDEF[type]?.[key] || ['', '']
    const vi = c?.[`${key}_vi`] ?? d[0]
    const en = c?.[`${key}_en`] ?? d[1]
    return bilingual && en ? `${vi} / ${en}` : vi
  }
  const field = (type, c, key, value) => (
    <div className="rcp__field"><b>{lbl(type, c, key)}:</b> {value || '—'}</div>
  )

  const renderBlock = (blk) => {
    const c = blk.content || {}
    switch (blk.type) {
      case 'logo': {
        const dv = c.title_vi ?? 'BIÊN NHẬN'
        const de = c.title_en ?? 'RECEIPT'
        return (
          <div className="rcp__header">
            {config.logo_url ? (
              <img className="rcp__logo-img" src={config.logo_url} alt={c.shop_name || 'logo'} />
            ) : (
              c.logo_text && <div className="rcp__logo">{c.logo_text}</div>
            )}
            {c.shop_name && <div className="rcp__brand">{c.shop_name}</div>}
            {(dv || de) && <div className="rcp__title">{bilingual && de ? `${de} — ${dv}` : dv}</div>}
          </div>
        )
      }
      case 'customer_info':
        return (
          <div className="rcp__info">
            {field('customer_info', c, 'name', order.customer_name)}
            {field('customer_info', c, 'tel', order.customer_phone)}
          </div>
        )
      case 'receiving_time':
        return field('receiving_time', c, 'label', formatPickupShort(order.created_at))
      case 'delivery_time':
        return field('delivery_time', c, 'label', order.pickup_at ? formatPickupShort(order.pickup_at) : '')
      case 'items_table':
        return (
          <table className="rcp__table">
            <thead>
              <tr>
                <th className="rcp__th rcp__th--name">{thLabel('items_table', c, 'svc')}</th>
                <th className="rcp__th rcp__th--qty">{thLabel('items_table', c, 'qty')}</th>
                <th className="rcp__th rcp__th--num">{thLabel('items_table', c, 'price')}</th>
                <th className="rcp__th rcp__th--num">{thLabel('items_table', c, 'total')}</th>
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
            <div className="rcp__row"><span>{lbl('totals', c, 'subtotal')}</span><span>{formatVND(subtotal)}</span></div>
            {surcharge > 0 && (
              <div className="rcp__row"><span>{lbl('totals', c, 'surcharge')}{order.surcharge_reason ? ` (${order.surcharge_reason})` : ''}</span><span>+{formatVND(surcharge)}</span></div>
            )}
            {discount > 0 && (
              <div className="rcp__row"><span>{lbl('totals', c, 'discount')}{order.discount_reason ? ` (${order.discount_reason})` : ''}</span><span>−{formatVND(discount)}</span></div>
            )}
            <div className="rcp__row rcp__row--total"><span>{lbl('totals', c, 'total')}</span><span>{formatVND(grandTotal)}</span></div>
          </div>
        )
      case 'surcharge_discount':
        if (surcharge <= 0 && discount <= 0) return null
        return (
          <div className="rcp__promo">
            {surcharge > 0 && <div className="rcp__row"><span>{lbl('surcharge_discount', c, 'sur')}{order.surcharge_reason ? ` (${order.surcharge_reason})` : ''}</span><span>+{formatVND(surcharge)}</span></div>}
            {discount > 0 && <div className="rcp__row"><span>{lbl('surcharge_discount', c, 'dis')}{order.discount_reason ? ` (${order.discount_reason})` : ''}</span><span>−{formatVND(discount)}</span></div>}
          </div>
        )
      case 'payment_status': {
        const [vi, en] = PAY_STATUS[order.payment_status] || PAY_STATUS.unpaid
        return <div className="rcp__paystatus">{bilingual ? `${vi} / ${en}` : vi}</div>
      }
      case 'note': {
        if (!c.vi && !c.en) return null
        return (
          <div className="rcp__note">
            <div className="rcp__note-label">{lbl('note', c, 'label')}</div>
            {c.vi && <div className="rcp__note-vi">{c.vi}</div>}
            {bilingual && c.en && <div className="rcp__note-en">{c.en}</div>}
          </div>
        )
      }
      case 'qr_tracking':
        return (
          <div className="rcp__qr">
            <QRCodeSVG value={trackUrl} size={132} level="M" />
            <div className="rcp__qr-cap">{lbl('qr_tracking', c, 'cap')}</div>
          </div>
        )
      case 'order_no':
        return <div className="rcp__no">{lbl('order_no', c, 'label')}: <b>{order.order_code}</b></div>
      case 'footer_contact': {
        const rows = [
          ['lbl_hotline', c.hotline], ['lbl_web', c.web], ['lbl_address', c.address],
          ['lbl_zalo', c.zalo_wa_kakao], ['lbl_open', c.open_hours],
        ].filter(([, v]) => v && String(v).trim())
        if (!rows.length && !c.tagline) return null
        return (
          <div className="rcp__foot">
            {rows.map(([k, value]) => (
              <div className="rcp__foot-row" key={k}><span className="rcp__foot-label">{lbl('footer_contact', c, k)}:</span> {value}</div>
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
      case 'divider':
        return <div className={`rcp__hr rcp__hr--${c.style === 'solid' ? 'solid' : 'dashed'}`} />
      case 'spacer':
        return <div className={`rcp__spacer rcp__spacer--${c.height === 'medium' ? 'medium' : 'small'}`} />
      default:
        return null
    }
  }

  // header bảng món: nhãn vi (+ en nhỏ nếu song ngữ).
  function thLabel(type, c, key) {
    const d = LDEF[type]?.[key] || ['', '']
    const vi = c?.[`${key}_vi`] ?? d[0]
    const en = c?.[`${key}_en`] ?? d[1]
    return (
      <>
        {vi}
        {bilingual && en && <span className="rcp__th-en">{en}</span>}
      </>
    )
  }

  // class định dạng theo khối.
  const fmtClass = (blk) => {
    const align = blk.align || DEF_ALIGN[blk.type] || 'left'
    const size = blk.size || 'normal'
    return `rcp__fmt rcp__al-${align} rcp__sz-${size}${blk.bold ? ' rcp__bold' : ''}`
  }

  // Gom khối ĐANG BẬT theo hàng; trong hàng: left → right. Tự chèn kẻ mảnh giữa
  // các hàng (bỏ qua quanh khối divider/spacer để không trùng đường kẻ).
  const enabled = blocks.filter((b) => b.enabled)
  const rowsMap = new Map()
  enabled.forEach((b) => {
    const r = b.row ?? 0
    if (!rowsMap.has(r)) rowsMap.set(r, [])
    rowsMap.get(r).push(b)
  })
  const colOrder = { left: 0, full: 0, right: 1 }
  const nodes = []
  let prevDecor = false
  ;[...rowsMap.keys()].sort((a, b) => a - b).forEach((rk) => {
    const cells = rowsMap.get(rk).slice().sort((a, b) => (colOrder[a.col] ?? 0) - (colOrder[b.col] ?? 0))
    const rendered = cells.map((b) => ({ b, el: renderBlock(b) })).filter((x) => x.el)
    if (!rendered.length) return
    const decor = cells.every((b) => b.type === 'divider' || b.type === 'spacer')
    if (nodes.length && !decor && !prevDecor) nodes.push(<div className="rcp__divider" key={`d-${rk}`} />)
    if (rendered.length === 1) {
      nodes.push(<div className={fmtClass(rendered[0].b)} key={`r-${rk}`}>{rendered[0].el}</div>)
    } else {
      nodes.push(
        <div className="rcp__brow" key={`r-${rk}`}>
          {rendered.map((x) => (
            <div className={`rcp__bcell ${fmtClass(x.b)}`} key={x.b.id}>{x.el}</div>
          ))}
        </div>,
      )
    }
    prevDecor = decor
  })

  return <div className="rcp">{nodes}</div>
}
