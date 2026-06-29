import { useEffect, useRef, useState } from 'react'
import { getPrintChannel } from '../lib/platform'

// ⚠️ TẠM (test môi trường) — GỠ sau khi xác nhận native vs web trên máy thật.
// Badge nhỏ góc dưới phải: hiện kênh in "IN: native" (vỏ Capacitor) / "IN: web" (PWA/browser, T1).
// Khi URL có ?debug=1 VÀ đang native: thêm DẢI DEBUG rộng (nút TEST IN + Xoá log + vùng log) ở
// bottom:60px, kéo gần hết bề ngang để DỄ ĐỌC trên màn ngang T2 (gọi THẲNG plugin Sunmi, in trực
// tiếp không buffer). Mọi thứ trong #root → @media print ẩn (#root display:none) nên KHÔNG in ra.

export default function PlatformBadge() {
  const channel = getPrintChannel()
  const debug =
    typeof window !== 'undefined' && /[?&]debug=1(\b|&|$)/.test(window.location.search)
  const showTest = debug && channel === 'native'
  const [log, setLog] = useState([])
  const logRef = useRef(null)

  // Giữ tối đa 30 dòng gần nhất; dòng mới nhất ở DƯỚI.
  const append = (line) => setLog((prev) => [...prev, line].slice(-30))
  const clearLog = () => setLog([])

  // Tự cuộn xuống dòng mới nhất mỗi khi log đổi.
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

      {/* DẢI DEBUG (chỉ ?debug=1 + native) — rộng gần hết bề ngang, cao hơn mép để không bị cắt. */}
      {showTest && (
        <div
          style={{
            position: 'fixed',
            left: 8,
            right: 8,
            bottom: 60,
            zIndex: 2147483647,
            display: 'flex',
            flexDirection: 'column',
            gap: 6,
            pointerEvents: 'none', // chỉ nút + log bật lại auto
            userSelect: 'none',
          }}
        >
          <div style={{ display: 'flex', gap: 8, justifyContent: 'flex-end', pointerEvents: 'auto' }}>
            <button
              type="button"
              onClick={clearLog}
              style={{
                padding: '6px 12px',
                borderRadius: 6,
                background: '#475569',
                color: '#fff',
                border: 'none',
                font: '700 13px system-ui, -apple-system, sans-serif',
              }}
            >
              Xoá log
            </button>
            <button
              type="button"
              onClick={testPrint}
              style={{
                padding: '6px 16px',
                borderRadius: 6,
                background: '#16a34a',
                color: '#fff',
                border: 'none',
                font: '700 13px system-ui, -apple-system, sans-serif',
              }}
            >
              TEST IN
            </button>
          </div>
          <div
            ref={logRef}
            style={{
              pointerEvents: 'auto',
              background: '#000',
              color: '#0f0',
              font: '13px/1.45 ui-monospace, Menlo, Consolas, monospace',
              padding: '8px 10px',
              borderRadius: 6,
              border: '2px solid #0f0',
              maxHeight: 200,
              overflowY: 'auto',
              whiteSpace: 'pre-wrap',
              wordBreak: 'break-word',
            }}
          >
            {log.length ? log.join('\n') : '(log trống — bấm TEST IN)'}
          </div>
        </div>
      )}
    </>
  )
}
