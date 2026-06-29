import { useEffect, useRef } from 'react'
import BillContent from './Bill'
import { useCurrentNativeJob, finishNativeJob } from '../lib/nativePrintStore'
import { captureNodeCentered } from '../lib/captureBill'
import { dbg } from '../lib/debugLog' // ⚠️ TẠM — chẩn đoán native print

// Thông số ĐÃ TEST (khớp node debug PlatformBadge): vùng in 576 dots, lề đệm 16px(2mm) mỗi bên,
// nội dung 544px = 68mm. Render node ở 68mm (font GIỮ NGUYÊN) → scale 8 dot/mm = cỡ chữ T1.
const PRINTABLE_DOTS = 576
const SIDE_MARGIN_PX = 16
const BILL_WIDTH = PRINTABLE_DOTS - 2 * SIDE_MARGIN_PX // 544
const BILL_WIDTH_MM = BILL_WIDTH / 8 // 68

// Lớp IN NATIVE (printBitmap). Mount 1 lần ở App. Khi store có job native → render node bill
// off-screen 68mm với DATA THẬT (qrRenderer='canvas' để html2canvas giữ QR) → chụp → printBitmap +
// cutPaper → finishNativeJob(). 3d-1: CHỈ mode 'bill'; mode khác (lien2) → bỏ qua + markDone (queue
// đã fallback web cho non-bill nên thực tế không vào đây). LUÔN finishNativeJob (try/finally) → không kẹt.
export default function NativePrintLayer() {
  const job = useCurrentNativeJob()
  const nodeRef = useRef(null)
  const handledRef = useRef(null) // job đã xử lý (chống chụp/in chồng)

  useEffect(() => {
    if (!job) return undefined
    if (handledRef.current === job) return undefined // job này đã xử
    handledRef.current = job
    let cancelled = false
    dbg(`NATIVE layer: nhan job mode=${job.mode} order=${job.order?.order_code || 'NULL'}`)

    if (job.mode !== 'bill' || !job.order) {
      dbg('NATIVE layer: bo qua (mode!=bill hoac thieu order) → markDone')
      finishNativeJob() // chưa hỗ trợ / thiếu data → bỏ qua an toàn
      return undefined
    }

    // chờ 2 frame: React commit + layout + QRCodeCanvas vẽ xong rồi mới chụp
    const raf1 = requestAnimationFrame(() => {
      requestAnimationFrame(async () => {
        if (cancelled) return
        try {
          const node = nodeRef.current
          if (!node) throw new Error('node native rỗng')
          // ⚠️ TẠM — CHẨN ĐOÁN LOGO: config có logo_url? img render? load được? URL tuyệt đối ảnh
          // đang trỏ tới (nghi APK webview resolve "/uploads/" sai base → 404 → mất logo).
          const logImgs = (tag) => {
            const imgs = Array.from(node.querySelectorAll('img'))
            dbg(`[${tag}] imgs=${imgs.length}`)
            imgs.forEach((im, i) => {
              let abs = ''
              try {
                abs = new URL(im.getAttribute('src') || '', window.location.href).href
              } catch {
                abs = 'URLerr'
              }
              dbg(`  [${tag}] img${i} comp=${im.complete} nat=${im.naturalWidth}x${im.naturalHeight} lay=${im.width}x${im.height} abs=${abs.slice(0, 90)}`)
            })
          }
          dbg(`NATIVE cfg.logo_url=${job.config?.logo_url || 'NULL'}`)
          dbg(`NATIVE origin=${window.location.origin} href=${window.location.href.slice(0, 70)}`)
          logImgs('truoc')
          const scale = BILL_WIDTH / node.offsetWidth // 68mm → 544px (8 dot/mm = cỡ chữ T1)
          const { dataUrl } = await captureNodeCentered(node, { scale, canvasWidth: PRINTABLE_DOTS })
          logImgs('sau') // sau khi _waitImages + chụp → nat/comp phản ánh ảnh đã load chưa
          const base64 = dataUrl.replace(/^data:image\/[a-z]+;base64,/, '')
          dbg(`NATIVE: da chup base64 len=${base64.length} → goi printBitmap...`)
          const p = typeof window !== 'undefined' && window.Capacitor?.Plugins?.SunmiPrinter
          if (!p) throw new Error('KHONG thay SunmiPrinter')
          await p.printBitmap({ bitmap: base64 })
          await p.lineWrap({ lines: 3 })
          await p.cutPaper()
          dbg('NATIVE: printBitmap + cutPaper OK')
        } catch (e) {
          dbg('NATIVE LOI: ' + (e && e.message ? e.message : String(e)))
        } finally {
          if (!cancelled) finishNativeJob() // LUÔN markDone → queue không kẹt
        }
      })
    })
    return () => {
      cancelled = true
      cancelAnimationFrame(raf1)
    }
  }, [job])

  // Chỉ render node khi có job bill hợp lệ (data thật). Off-screen, hiển thị THẬT (không display:none).
  if (!job || job.mode !== 'bill' || !job.order) return null
  return (
    <div
      ref={nodeRef}
      aria-hidden="true"
      style={{ position: 'fixed', left: -9999, top: 0, width: `${BILL_WIDTH_MM}mm`, background: '#fff' }}
    >
      <BillContent qrRenderer="canvas" order={job.order} config={job.config} />
    </div>
  )
}
