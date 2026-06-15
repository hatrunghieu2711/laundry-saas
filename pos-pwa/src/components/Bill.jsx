import { QRCodeSVG } from 'qrcode.react'
import { formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'

// Phiếu (.rcp) THEO KHỐI (Stage 5.6 → 5.8). Render từ config.blocks: thứ tự hàng,
// 2 khối/hàng (ghép tự do), nhãn sửa được (fallback LDEF), định dạng theo khối.
// 5.8: Tên/ĐT là 2 khối; KHÔNG kẻ ngang tự động; bold tách nhãn vs giá trị (khối
// field); dòng Tạm tính/Phụ thu/Giảm CHỈ hiện khi đơn có phụ thu/giảm.
const FIELD_TYPES = new Set(['customer_name', 'customer_phone', 'receiving_time', 'delivery_time', 'order_no'])
const PAY_STATUS = {
  paid: ['ĐÃ THANH TOÁN', 'PAID'], partial: ['THANH TOÁN MỘT PHẦN', 'PARTIALLY PAID'],
  unpaid: ['CHƯA THANH TOÁN', 'UNPAID'], debt: ['GHI NỢ', 'ON CREDIT'],
  refunded: ['ĐÃ HOÀN TIỀN', 'REFUNDED'],
}
const LDEF = {
  logo: { title: ['BIÊN NHẬN', 'RECEIPT'] },
  customer_name: { label: ['Tên', 'Name'] },
  customer_phone: { label: ['ĐT', 'Tel'] },
  receiving_time: { label: ['Giờ nhận', 'Receiving'] },
  delivery_time: { label: ['Giờ giao', 'Delivery'] },
  items_table: { svc: ['Dịch vụ', 'Service'], qty: ['SL', 'Qty'], price: ['Giá', 'Price'], total: ['Tổng', 'Total'] },
  totals: { subtotal: ['Tạm tính', 'Subtotal'], surcharge: ['Phụ thu', 'Surcharge'], discount: ['Giảm', 'Discount'], total: ['TỔNG CỘNG', 'TOTAL'] },
  qr_tracking: { cap: ['Quét mã QR', 'Scan QR to track'] },
  order_no: { label: ['Số', 'No'] },
}
const DEF_ALIGN = { logo: 'center', qr_tracking: 'center', order_no: 'center', payment_status: 'center', custom_text: 'center' }

export default function BillContent({ config, order }) {
  if (!order) return null
  const bilingual = config?.bilingual !== false
  const blocks = Array.isArray(config?.blocks) ? config.blocks : []

  const grandTotal = toNumber(order.total_amount)
  const surcharge = toNumber(order.surcharge_amount)
  const discount = toNumber(order.discount_amount)
  const subtotal = order.subtotal != null ? toNumber(order.subtotal) : grandTotal
  const hasAdj = surcharge > 0 || discount > 0
  const trackBase = import.meta.env.VITE_TRACK_BASE_URL || 'https://track.giatui2h.com'
  const trackUrl = `${trackBase}/track/${order.order_code}`

  const lbl = (type, c, key) => {
    const d = LDEF[type]?.[key] || ['', '']
    const vi = c?.[`${key}_vi`] ?? d[0]
    const en = c?.[`${key}_en`] ?? d[1]
    return bilingual && en ? `${vi} / ${en}` : vi
  }
  // Khối có nhãn + giá trị (span riêng để tô đậm nhãn / giá trị độc lập).
  const field = (type, c, value, wrapClass = 'rcp__field') => (
    <div className={wrapClass}>
      <span className="rcp__lbl">{lbl(type, c, 'label')}:</span>{' '}
      <span className="rcp__val">{value || '—'}</span>
    </div>
  )
  const thLabel = (type, c, key) => {
    const d = LDEF[type]?.[key] || ['', '']
    const vi = c?.[`${key}_vi`] ?? d[0]
    const en = c?.[`${key}_en`] ?? d[1]
    return <>{vi}{bilingual && en && <span className="rcp__th-en">{en}</span>}</>
  }

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
      case 'customer_name':
        return field('customer_name', c, order.customer_name)
      case 'customer_phone':
        return field('customer_phone', c, order.customer_phone)
      case 'receiving_time':
        return field('receiving_time', c, formatPickupShort(order.created_at))
      case 'delivery_time':
        return field('delivery_time', c, order.pickup_at ? formatPickupShort(order.pickup_at) : '')
      case 'order_no':
        return field('order_no', c, order.order_code, 'rcp__no')
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
        // Tạm tính / Phụ thu / Giảm CHỈ hiện khi đơn thật sự có phụ thu/giảm.
        return (
          <div className="rcp__totals">
            {hasAdj && <div className="rcp__row"><span>{lbl('totals', c, 'subtotal')}</span><span>{formatVND(subtotal)}</span></div>}
            {surcharge > 0 && (
              <div className="rcp__row"><span>{lbl('totals', c, 'surcharge')}{order.surcharge_reason ? ` (${order.surcharge_reason})` : ''}</span><span>+{formatVND(surcharge)}</span></div>
            )}
            {discount > 0 && (
              <div className="rcp__row"><span>{lbl('totals', c, 'discount')}{order.discount_reason ? ` (${order.discount_reason})` : ''}</span><span>−{formatVND(discount)}</span></div>
            )}
            <div className="rcp__row rcp__row--total"><span>{lbl('totals', c, 'total')}</span><span>{formatVND(grandTotal)}</span></div>
          </div>
        )
      case 'payment_status': {
        const [vi, en] = PAY_STATUS[order.payment_status] || PAY_STATUS.unpaid
        return <div className="rcp__paystatus">{bilingual ? `${vi} / ${en}` : vi}</div>
      }
      case 'qr_tracking':
        return (
          <div className="rcp__qr">
            <QRCodeSVG value={trackUrl} size={132} level="M" />
            <div className="rcp__qr-cap">{lbl('qr_tracking', c, 'cap')}</div>
          </div>
        )
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

  // class định dạng theo khối. Khối field: bold tách nhãn/giá trị (None→fallback bold).
  const fmtClass = (blk) => {
    const align = blk.align || DEF_ALIGN[blk.type] || 'left'
    const size = blk.size || 'normal'
    let cls = `rcp__fmt rcp__al-${align} rcp__sz-${size}`
    if (FIELD_TYPES.has(blk.type)) {
      if (blk.bold_label ?? blk.bold) cls += ' rcp__lblbold'
      if (blk.bold_value ?? blk.bold) cls += ' rcp__valbold'
    } else if (blk.bold) {
      cls += ' rcp__bold'
    }
    return cls
  }

  // Gom khối ĐANG BẬT theo hàng; trong hàng: left → right. KHÔNG kẻ ngang tự động
  // (Stage 5.8) — kẻ chỉ từ khối divider owner chèn.
  const rowsMap = new Map()
  blocks.filter((b) => b.enabled).forEach((b) => {
    const r = b.row ?? 0
    if (!rowsMap.has(r)) rowsMap.set(r, [])
    rowsMap.get(r).push(b)
  })
  const colOrder = { left: 0, full: 0, right: 1 }
  const nodes = []
  ;[...rowsMap.keys()].sort((a, b) => a - b).forEach((rk) => {
    const cells = rowsMap.get(rk).slice().sort((a, b) => (colOrder[a.col] ?? 0) - (colOrder[b.col] ?? 0))
    const rendered = cells.map((b) => ({ b, el: renderBlock(b) })).filter((x) => x.el)
    if (!rendered.length) return
    if (rendered.length === 1) {
      nodes.push(<div className={fmtClass(rendered[0].b)} key={`r-${rk}`}>{rendered[0].el}</div>)
    } else {
      nodes.push(
        <div className="rcp__brow" key={`r-${rk}`}>
          {rendered.map((x) => <div className={`rcp__bcell ${fmtClass(x.b)}`} key={x.b.id}>{x.el}</div>)}
        </div>,
      )
    }
  })

  return <div className="rcp">{nodes}</div>
}
