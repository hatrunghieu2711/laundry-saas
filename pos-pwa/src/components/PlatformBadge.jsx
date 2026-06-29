import { useEffect, useRef, useState } from 'react'
import BillContent from './Bill'
import { getPrintChannel } from '../lib/platform'
import { DEFAULT_RECEIPT } from '../lib/receipt'
import { captureNodeCentered } from '../lib/captureBill'

// ⚠️ TẠM (test môi trường + GĐ3) — GỠ sau khi xong.
// Badge nhỏ góc dưới phải: kênh in "IN: native"/"IN: web".
// Khi ?debug=1 + native: DẢI DEBUG (TEST IN / CHỤP BILL / Xoá + log + ảnh preview) + 1 NODE BILL
// off-screen 576px (= vùng in 72mm @ 8dot/mm) để html2canvas chụp kiểm layout (CHƯA in).
// Mọi thứ trong #root → @media print ẩn (#root display:none) nên KHÔNG in ra phiếu.

// Đơn MẪU hardcode (đủ field BillContent cần) — 3b chỉ kiểm layout, không cần đơn thật.
const SAMPLE_ORDER = {
  order_code: 'TEST-001',
  customer_name: 'Nguyen Van A',
  customer_phone: '0901234567',
  created_at: '2026-06-29T08:30:00+07:00',
  pickup_at: '2026-06-30T17:00:00+07:00',
  branch_id: 0,
  payment_status: 'unpaid',
  subtotal: 150000,
  surcharge_amount: 0,
  discount_amount: 0,
  total_amount: 150000,
  surcharge_reason: '',
  discount_reason: '',
  items: [
    { id: 1, service_name: 'Giặt sấy thường', quantity: 3, unit_price: 30000, subtotal: 90000 },
    { id: 2, service_name: 'Hấp áo vest', quantity: 2, unit_price: 30000, subtotal: 60000 },
  ],
}

// LỀ ĐỆM DUNG SAI: lề T2 KHÔNG ổn định (giấy xê dịch mỗi lần in) → KHÔNG in đầy 576. Thu nội dung
// hẹp lại, chừa lề trắng đều mỗi bên → giấy xê dịch trong khoảng đó vẫn không cắt/không lộ lệch.
const PRINTABLE_DOTS = 576 // vùng in máy (dots) — KHÔNG vượt → tránh cắt mép (canvas 640 từng bị cắt)
const SIDE_MARGIN_PX = 16 // lề đệm MỖI BÊN: 16px = 2mm @8dot/mm. ⬆️ tăng nếu cần đệm dày hơn (vd 24=3mm)
const BILL_WIDTH = PRINTABLE_DOTS - 2 * SIDE_MARGIN_PX // = 544 dots (nội dung)
const BILL_WIDTH_MM = BILL_WIDTH / 8 // = 68mm — render node ĐÚNG mm này → GIỮ cỡ chữ T1 (8 dot/mm)

export default function PlatformBadge() {
  const channel = getPrintChannel()
  const debug =
    typeof window !== 'undefined' && /[?&]debug=1(\b|&|$)/.test(window.location.search)
  const showTest = debug && channel === 'native'
  const [log, setLog] = useState([])
  const [preview, setPreview] = useState(null)
  const logRef = useRef(null)
  const billRef = useRef(null)

  const append = (line) => setLog((prev) => [...prev, line].slice(-30))
  const clearAll = () => {
    setLog([])
    setPreview(null)
  }

  useEffect(() => {
    const el = logRef.current
    if (el) el.scrollTop = el.scrollHeight
  }, [log])

  const testPrint = async () => {
    append('--- TEST IN (web remote) ---')
    const p = typeof window !== 'undefined' && window.Capacitor?.Plugins?.SunmiPrinter
    if (!p) {
      append('KHONG thay SunmiPlugin tu web remote')
      return
    }
    try {
      append('goi getPrinterModel...')
      const model = await p.getPrinterModel()
      append('getPrinterModel: ' + JSON.stringify(model))
      await p.setAlignment({ alignment: 'center' })
      append('setAlignment center OK')
      await p.setFontSize({ size: 32 })
      append('setFontSize 32 OK')
      await p.printText({ text: 'GIAT UI 2H\n' })
      append('printText 1 OK')
      await p.printText({ text: 'Test tu WEB REMOTE\n' })
      append('printText 2 OK')
      await p.lineWrap({ lines: 3 })
      append('lineWrap 3 OK')
      await p.cutPaper()
      append('cutPaper OK')
      append('==> HOAN TAT: da gui in + cat giay')
    } catch (e) {
      append('LOI: ' + (e && e.message ? e.message : String(e)))
      try {
        append('LOI raw: ' + JSON.stringify(e, Object.getOwnPropertyNames(e || {})))
      } catch {
        /* noop */
      }
    }
  }

  // 3c: chụp node bill → base64 PNG (BỎ tiền tố data:) → printBitmap + cutPaper (IN TRỰC TIẾP,
  // KHÔNG enterPrinterBuffer — buffer gây treo, đã chứng minh 2b). printBitmap({bitmap}) của
  // @kduma-autoid/capacitor-sunmi-printer nhận base64 THUẦN; width 576px = chuẩn giấy 80mm.
  const printBitmapTest = async () => {
    append('--- IN BITMAP (web remote) ---')
    const p = typeof window !== 'undefined' && window.Capacitor?.Plugins?.SunmiPrinter
    if (!p) {
      append('KHONG thay SunmiPlugin tu web remote')
      return
    }
    const node = billRef.current
    if (!node) {
      append('node bill rỗng')
      return
    }
    try {
      append('chup node...')
      const scale = BILL_WIDTH / node.offsetWidth // node 68mm(~257px) → 544px (8 dot/mm = cỡ chữ T1)
      const { dataUrl, width, height, billWidth, dx, left, right } = await captureNodeCentered(node, {
        scale,
        canvasWidth: PRINTABLE_DOTS,
        analyze: true,
      })
      setPreview(dataUrl)
      append(`vung in ${width}, bill ${billWidth}px(${BILL_WIDTH_MM}mm), le dem ${dx}px(2mm) | le anh TRAI=${left} PHAI=${right}`)
      // base64 THUẦN — printBitmap KHÔNG nhận tiền tố "data:image/png;base64,"
      const base64 = dataUrl.replace(/^data:image\/[a-z]+;base64,/, '')
      append(`base64 len=${base64.length}`)
      try {
        const paper = await p.getPrinterPaper()
        append('getPrinterPaper: ' + JSON.stringify(paper))
      } catch (e) {
        append('getPrinterPaper loi: ' + (e && e.message ? e.message : String(e)))
      }
      append('goi printBitmap...') // ảnh ĐÃ tự canh giữa → KHÔNG cần setAlignment
      await p.printBitmap({ bitmap: base64 })
      append('printBitmap OK')
      await p.lineWrap({ lines: 3 })
      append('lineWrap 3 OK')
      await p.cutPaper()
      append('==> HOAN TAT: in bitmap + cat giay')
    } catch (e) {
      append('LOI: ' + (e && e.message ? e.message : String(e)))
      try {
        append('LOI raw: ' + JSON.stringify(e, Object.getOwnPropertyNames(e || {})))
      } catch {
        /* noop */
      }
    }
  }

  // 3b: chụp NODE BILL off-screen (576px) → ảnh PNG → hiện <img> preview. KHÔNG gửi máy in.
  const captureBill = async () => {
    append('--- CHỤP BILL (html2canvas) ---')
    const node = billRef.current
    if (!node) {
      append('node bill rỗng')
      return
    }
    try {
      const scale = BILL_WIDTH / node.offsetWidth // node 68mm(~257px) → 544px (8 dot/mm = cỡ chữ T1)
      const { dataUrl, width, height, billWidth, dx, left, right } = await captureNodeCentered(node, {
        scale,
        canvasWidth: PRINTABLE_DOTS,
        analyze: true,
      })
      setPreview(dataUrl)
      append(`vung in ${width}, bill ${billWidth}px(${BILL_WIDTH_MM}mm), le dem ${dx}px | le anh TRAI=${left} PHAI=${right}`)
    } catch (e) {
      append('LOI chup: ' + (e && e.message ? e.message : String(e)))
    }
  }

  return (
    <>
      {/* Badge nhỏ góc dưới phải — luôn hiện (web + native), KHÔNG chặn thao tác. */}
      <div
        aria-hidden="true"
        style={{
          position: 'fixed',
          right: 6,
          bottom: 6,
          zIndex: 2147483647,
          padding: '2px 8px',
          borderRadius: 6,
          background: 'rgba(15, 23, 42, 0.72)',
          color: '#fff',
          font: '600 11px system-ui, -apple-system, sans-serif',
          letterSpacing: '0.02em',
          pointerEvents: 'none',
          userSelect: 'none',
        }}
      >
        IN: {channel}
      </div>

      {showTest && (
        <>
          {/* NODE BILL off-screen 576px — hiển thị THẬT (left:-9999) để html2canvas chụp được. */}
          <div
            ref={billRef}
            style={{
              position: 'fixed',
              left: -9999,
              top: 0,
              width: `${BILL_WIDTH_MM}mm`, // 68mm: font 12px GIỮ NGUYÊN → scale 8dot/mm = cỡ chữ T1; hẹp hơn 72mm để có lề đệm
              background: '#fff',
            }}
          >
            <BillContent config={DEFAULT_RECEIPT} order={SAMPLE_ORDER} qrRenderer="canvas" />
          </div>

          {/* DẢI DEBUG — rộng gần hết bề ngang, panel cuộn được. */}
          <div
            style={{
              position: 'fixed',
              left: 8,
              right: 8,
              bottom: 60,
              zIndex: 2147483647,
              pointerEvents: 'none',
            }}
          >
            <div
              style={{
                pointerEvents: 'auto',
                display: 'flex',
                flexDirection: 'column',
                gap: 6,
                maxHeight: '74vh',
                overflowY: 'auto',
              }}
            >
              <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap' }}>
                <button type="button" onClick={clearAll} style={btn('#475569')}>Xoá</button>
                <button type="button" onClick={captureBill} style={btn('#2563eb')}>CHỤP BILL</button>
                <button type="button" onClick={printBitmapTest} style={btn('#ea580c')}>IN BITMAP</button>
                <button type="button" onClick={testPrint} style={btn('#16a34a')}>TEST IN</button>
              </div>
              <div
                ref={logRef}
                style={{
                  background: '#000',
                  color: '#0f0',
                  font: '13px/1.45 ui-monospace, Menlo, Consolas, monospace',
                  padding: '8px 10px',
                  borderRadius: 6,
                  border: '2px solid #0f0',
                  maxHeight: 180,
                  overflowY: 'auto',
                  whiteSpace: 'pre-wrap',
                  wordBreak: 'break-word',
                }}
              >
                {log.length ? log.join('\n') : '(log trống — bấm TEST IN / CHỤP BILL)'}
              </div>
              {preview && (
                <img
                  src={preview}
                  alt="bill preview"
                  style={{
                    display: 'block',
                    maxWidth: '100%',
                    background: '#fff',
                    border: '2px solid #22d3ee',
                    borderRadius: 4,
                  }}
                />
              )}
            </div>
          </div>
        </>
      )}
    </>
  )
}

// helper style nút (dải debug)
function btn(bg) {
  return {
    padding: '6px 14px',
    borderRadius: 6,
    background: bg,
    color: '#fff',
    border: 'none',
    font: '700 13px system-ui, -apple-system, sans-serif',
  }
}
