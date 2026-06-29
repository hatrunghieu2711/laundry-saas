import { useEffect, useRef, useState } from 'react'
import BillContent from './Bill'
import { getPrintChannel, isNativePlatform, nativePrintActive } from '../lib/platform'
import { DEFAULT_RECEIPT } from '../lib/receipt'
import { captureNodeCentered } from '../lib/captureBill'
import { useDebugVersion, getDebugLog, dbg } from '../lib/debugLog'

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
  // debug BỀN qua điều hướng: ?debug=1 → bật + lưu localStorage.debug; ?debug=0 → tắt + xóa.
  // debug = (URL debug=1) || localStorage.debug==='1' (trừ khi URL debug=0) → panel sống sót route
  // (React Router rụng query khi chuyển trang). Đồng bộ cơ chế với nativeprint.
  const urlDebug1 = typeof window !== 'undefined' && /[?&]debug=1(\b|&|$)/.test(window.location.search)
  const urlDebug0 = typeof window !== 'undefined' && /[?&]debug=0(\b|&|$)/.test(window.location.search)
  let lsDebug = false
  try {
    lsDebug = typeof window !== 'undefined' && !!window.localStorage && window.localStorage.getItem('debug') === '1'
  } catch {
    /* noop */
  }
  const debug = urlDebug0 ? false : urlDebug1 || lsDebug
  const showTest = debug && channel === 'native'
  const [log, setLog] = useState([])
  const [preview, setPreview] = useState(null)
  const [panelOpen, setPanelOpen] = useState(true) // thu/mở panel log để bấm nút app phía sau
  const logRef = useRef(null)
  const billRef = useRef(null)

  // ⚠️ CHẨN ĐOÁN native-detection — re-render khi có dbg() từ module khác.
  useDebugVersion()
  // Đồng bộ localStorage.debug theo ?debug=1/0 (1 lần khi URL có param) → bền qua điều hướng.
  useEffect(() => {
    try {
      if (urlDebug1) window.localStorage.setItem('debug', '1')
      else if (urlDebug0) window.localStorage.removeItem('debug')
    } catch {
      /* noop */
    }
  }, [urlDebug1, urlDebug0])
  const search = typeof window !== 'undefined' ? window.location.search : ''
  const ls = typeof window !== 'undefined' && window.localStorage ? window.localStorage.getItem('nativeprint') : null
  const nat = isNativePlatform()
  const act = nativePrintActive()

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

      {/* NODE BILL off-screen — chỉ native (để html2canvas chụp). */}
      {showTest && (
        <div
          ref={billRef}
          style={{
            position: 'fixed',
            left: -9999,
            top: 0,
            width: `${BILL_WIDTH_MM}mm`, // 68mm: giữ cỡ chữ T1 + lề đệm
            background: '#fff',
          }}
        >
          <BillContent config={DEFAULT_RECEIPT} order={SAMPLE_ORDER} qrRenderer="canvas" />
        </div>
      )}

      {/* DẢI DEBUG — hiện khi ?debug=1. CLICK-THROUGH: chỉ NÚT bấm được (pointerEvents:auto); chữ/log
          pointerEvents:none → bấm XUYÊN xuống nút app phía sau (In lại bill...). "Ẩn log" để thu gọn. */}
      {debug && (
        <div style={{ position: 'fixed', left: 8, right: 8, bottom: 60, zIndex: 2147483647, pointerEvents: 'none' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 6, pointerEvents: 'none' }}>
            {/* Hàng nút điều khiển — LUÔN hiện, bấm được. */}
            <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap', pointerEvents: 'auto' }}>
              <button type="button" onClick={() => setPanelOpen((v) => !v)} style={btn('#0ea5e9')}>
                {panelOpen ? 'Ẩn log ▾' : 'Hiện log ▴'}
              </button>
              <button
                type="button"
                onClick={() => {
                  const next = ls === '1' ? '0' : '1'
                  try {
                    window.localStorage.setItem('nativeprint', next)
                  } catch {
                    /* noop */
                  }
                  dbg(`set ls.nativeprint=${next} (reload de ap dung neu can)`)
                }}
                style={btn('#7c3aed')}
              >
                ls.nativeprint → {ls === '1' ? '0' : '1'}
              </button>
              <button
                type="button"
                onClick={() => {
                  try {
                    window.localStorage.removeItem('debug')
                  } catch {
                    /* noop */
                  }
                  dbg('tat debug (xoa localStorage.debug; neu URL con ?debug=1 thi dung ?debug=0)')
                }}
                style={btn('#b91c1c')}
              >
                Tắt debug
              </button>
            </div>

            {panelOpen && (
              <>
                {/* CHẨN ĐOÁN native-detection (click-through) */}
                <div
                  style={{
                    pointerEvents: 'none',
                    background: '#1e293b',
                    color: '#fde047',
                    font: '12px/1.4 ui-monospace, Menlo, Consolas, monospace',
                    padding: '6px 8px',
                    borderRadius: 6,
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {`native=${nat ? 'Y' : 'N'} nativePrintActive=${act ? 'Y' : 'N'} ls.nativeprint=${String(ls)}\nsearch="${search}"`}
                </div>
                {showTest && (
                  <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', flexWrap: 'wrap', pointerEvents: 'auto' }}>
                    <button type="button" onClick={clearAll} style={btn('#475569')}>Xoá</button>
                    <button type="button" onClick={captureBill} style={btn('#2563eb')}>CHỤP BILL</button>
                    <button type="button" onClick={printBitmapTest} style={btn('#ea580c')}>IN BITMAP</button>
                    <button type="button" onClick={testPrint} style={btn('#16a34a')}>TEST IN</button>
                  </div>
                )}
                {log.length > 0 && (
                  <div
                    ref={logRef}
                    style={{
                      pointerEvents: 'none',
                      background: '#000',
                      color: '#0f0',
                      font: '12px/1.4 ui-monospace, Menlo, Consolas, monospace',
                      padding: '8px 10px',
                      borderRadius: 6,
                      border: '2px solid #0f0',
                      maxHeight: 110,
                      overflow: 'hidden',
                      whiteSpace: 'pre-wrap',
                      wordBreak: 'break-word',
                    }}
                  >
                    {log.slice(-8).join('\n')}
                  </div>
                )}
                {/* LOG DÙNG CHUNG — chẩn đoán; ~16 dòng cuối (click-through, không cuộn → bấm xuyên). */}
                <div
                  style={{
                    pointerEvents: 'none',
                    background: '#000',
                    color: '#38bdf8',
                    font: '12px/1.4 ui-monospace, Menlo, Consolas, monospace',
                    padding: '8px 10px',
                    borderRadius: 6,
                    border: '2px solid #38bdf8',
                    maxHeight: '46vh',
                    overflow: 'hidden',
                    whiteSpace: 'pre-wrap',
                    wordBreak: 'break-word',
                  }}
                >
                  {getDebugLog().length ? getDebugLog().slice(-16).join('\n') : '(dbg trống — bấm In bill)'}
                </div>
                {preview && (
                  <img
                    src={preview}
                    alt="bill preview"
                    style={{ pointerEvents: 'none', display: 'block', maxWidth: '100%', background: '#fff', border: '2px solid #22d3ee', borderRadius: 4 }}
                  />
                )}
              </>
            )}
          </div>
        </div>
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
