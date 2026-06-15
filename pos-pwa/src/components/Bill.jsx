import { QRCodeSVG } from 'qrcode.react'
import { formatVND, toNumber } from '../lib/format'
import { formatPickupShort } from '../lib/datetime'

// Phiếu (.rcp) SONG NGỮ Việt/Anh — layout CỐ ĐỊNH khớp mẫu Giặt Ủi 2H (Stage 5.3).
// Nhãn song ngữ cứng ở đây; owner chỉ sửa nội dung (text + logo) và bật/tắt
// khối ghi chú + phụ thu trong /settings/receipt. Dùng chung cho in + preview.
export default function BillContent({ config, order }) {
  if (!order) return null

  // Stage 5.4 — phụ thu/giảm là TIỀN THẬT, lấy snapshot từ đơn.
  const grandTotal = toNumber(order.total_amount)
  const surcharge = toNumber(order.surcharge_amount)
  const discount = toNumber(order.discount_amount)
  // subtotal: ưu tiên cột order.subtotal; fallback (đơn cũ chưa có) = total.
  const subtotal = order.subtotal != null ? toNumber(order.subtotal) : grandTotal

  // QR trỏ về trang tracking công khai (subdomain riêng), KHÔNG phải origin POS.
  const trackBase = import.meta.env.VITE_TRACK_BASE_URL || 'https://track.giatui2h.com'
  const trackUrl = `${trackBase}/track/${order.order_code}`

  const noteOn = !!config.note_enabled && (config.note_vi || config.note_en)

  // Một dòng chân phiếu song ngữ: chỉ hiện khi có giá trị.
  const footRows = [
    ['Hotline', config.hotline],
    ['Web', config.web],
    ['Địa chỉ / Add', config.address],
    ['Zalo / WA / Kakao', config.zalo_wa_kakao],
    ['Giờ mở cửa / OPEN', config.open_hours],
  ].filter(([, v]) => v && String(v).trim())

  return (
    <div className="rcp">
      {/* ── Logo + tiêu đề ─────────────────────────────────────────── */}
      <div className="rcp__header">
        {config.logo_url ? (
          <img className="rcp__logo-img" src={config.logo_url} alt={config.shop_name || 'logo'} />
        ) : (
          config.logo_text && <div className="rcp__logo">{config.logo_text}</div>
        )}
        {config.shop_name && <div className="rcp__brand">{config.shop_name}</div>}
        <div className="rcp__title">RECEIPT — BIÊN NHẬN</div>
      </div>

      <div className="rcp__divider" />

      {/* ── Khách + giờ nhận/giao ──────────────────────────────────── */}
      <div className="rcp__info">
        <div className="rcp__info-row">
          <span className="rcp__info-cell">
            <b>Tên / Name:</b> {order.customer_name || '—'}
          </span>
          <span className="rcp__info-cell">
            <b>ĐT / Tel:</b> {order.customer_phone || '—'}
          </span>
        </div>
        <div className="rcp__info-row">
          <span className="rcp__info-cell">
            <b>Giờ nhận / Receiving:</b> {formatPickupShort(order.created_at)}
          </span>
          <span className="rcp__info-cell">
            <b>Giờ giao / Delivery:</b> {order.pickup_at ? formatPickupShort(order.pickup_at) : '—'}
          </span>
        </div>
      </div>

      <div className="rcp__divider" />

      {/* ── Bảng món: Dịch vụ/SL/Giá/Tổng (Service/Qty/Price/Total) ──── */}
      <table className="rcp__table">
        <thead>
          <tr>
            <th className="rcp__th rcp__th--name">
              Dịch vụ<span className="rcp__th-en">Service</span>
            </th>
            <th className="rcp__th rcp__th--qty">
              SL<span className="rcp__th-en">Qty</span>
            </th>
            <th className="rcp__th rcp__th--num">
              Giá<span className="rcp__th-en">Price</span>
            </th>
            <th className="rcp__th rcp__th--num">
              Tổng<span className="rcp__th-en">Total</span>
            </th>
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

      {/* ── Tạm tính · (+Phụ thu) · (−Giảm) · Tổng cộng ────────────── */}
      <div className="rcp__totals">
        <div className="rcp__row">
          <span>Tạm tính / Subtotal</span>
          <span>{formatVND(subtotal)}</span>
        </div>
        {surcharge > 0 && (
          <div className="rcp__row">
            <span>
              + Phụ thu / Surcharge
              {order.surcharge_reason ? ` (${order.surcharge_reason})` : ''}
            </span>
            <span>{formatVND(surcharge)}</span>
          </div>
        )}
        {discount > 0 && (
          <div className="rcp__row">
            <span>
              − Giảm / Discount
              {order.discount_reason ? ` (${order.discount_reason})` : ''}
            </span>
            <span>−{formatVND(discount)}</span>
          </div>
        )}
        <div className="rcp__row rcp__row--total">
          <span>TỔNG CỘNG / TOTAL</span>
          <span>{formatVND(grandTotal)}</span>
        </div>
      </div>

      {/* ── Ghi chú trách nhiệm (song ngữ, in nghiêng) ─────────────── */}
      {noteOn && (
        <>
          <div className="rcp__divider" />
          <div className="rcp__note">
            <div className="rcp__note-label">Lưu ý / Important Note</div>
            {config.note_vi && <div className="rcp__note-vi">{config.note_vi}</div>}
            {config.note_en && <div className="rcp__note-en">{config.note_en}</div>}
          </div>
        </>
      )}

      <div className="rcp__divider" />

      {/* ── QR tracking ────────────────────────────────────────────── */}
      <div className="rcp__qr">
        <QRCodeSVG value={trackUrl} size={132} level="M" />
        <div className="rcp__qr-cap">Quét mã QR / Scan QR to track</div>
      </div>

      {/* ── Số đơn ─────────────────────────────────────────────────── */}
      <div className="rcp__no">
        Số / No: <b>{order.order_code}</b>
      </div>

      {/* ── Chân phiếu song ngữ ────────────────────────────────────── */}
      {(footRows.length > 0 || config.footer_text) && (
        <>
          <div className="rcp__divider" />
          <div className="rcp__foot">
            {footRows.map(([label, value]) => (
              <div className="rcp__foot-row" key={label}>
                <span className="rcp__foot-label">{label}:</span> {value}
              </div>
            ))}
            {config.footer_text && <div className="rcp__foot-tag">{config.footer_text}</div>}
          </div>
        </>
      )}
    </div>
  )
}
