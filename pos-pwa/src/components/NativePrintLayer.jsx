import { useEffect, useRef } from 'react'
import BillContent from './Bill'
import { Lien2LabelBody } from './Lien2Label'
import { ShiftSlipBody } from './ShiftSlip'
import { useCurrentNativeJob, finishNativeJob } from '../lib/nativePrintStore'
import { captureNodeCentered } from '../lib/captureBill'

// Thông số ĐÃ TEST: vùng in 576 dots, lề đệm 16px(2mm) mỗi bên,
// nội dung 544px = 68mm. Render node ở 68mm (font GIỮ NGUYÊN) → scale 8 dot/mm = cỡ chữ T1.
const PRINTABLE_DOTS = 576
const SIDE_MARGIN_PX = 16
const BILL_WIDTH = PRINTABLE_DOTS - 2 * SIDE_MARGIN_PX // 544
const BILL_WIDTH_MM = BILL_WIDTH / 8 // 68
const LABEL_WIDTH_MM = BILL_WIDTH_MM // nhãn cũng 68mm (portal thật .lbl 76mm → override xuống 68mm)

const SUPPORTED = new Set(['bill', 'lien2', 'shift'])

// Job có đủ DATA chưa: shift cần job.shift; bill/lien2 cần job.order.
function _hasData(job) {
  return job.mode === 'shift' ? !!job.shift : !!job.order
}

// Lớp IN NATIVE (printBitmap). Mount 1 lần ở App. Khi store có job native → render node off-screen
// 68mm với DATA THẬT (bill = BillContent qrRenderer='canvas'; nhãn = Lien2LabelBody widthMm=68) →
// captureBill (576/68mm/đệm) → printBitmap + cutPaper → finishNativeJob(). cutPaper mỗi job → cắt
// rời từng tờ (bill / từng nhãn). mode khác / thiếu order → bỏ qua + markDone. LUÔN finishNativeJob
// (try/finally) → KHÔNG kẹt queue.
export default function NativePrintLayer() {
  const job = useCurrentNativeJob()
  const nodeRef = useRef(null)
  const handledRef = useRef(null) // job đã xử lý (chống chụp/in chồng)

  useEffect(() => {
    if (!job) return undefined
    if (handledRef.current === job) return undefined // job này đã xử
    handledRef.current = job
    let cancelled = false

    if (!SUPPORTED.has(job.mode) || !_hasData(job)) {
      finishNativeJob() // chưa hỗ trợ / thiếu data → bỏ qua an toàn (không kẹt queue)
      return undefined
    }

    // chờ 2 frame: React commit + layout + QRCodeCanvas vẽ xong rồi mới chụp
    const raf1 = requestAnimationFrame(() => {
      requestAnimationFrame(async () => {
        if (cancelled) return
        try {
          const node = nodeRef.current
          if (!node) throw new Error('node native rỗng')
          const scale = BILL_WIDTH / node.offsetWidth // 68mm → 544px (8 dot/mm = cỡ chữ T1)
          const { dataUrl } = await captureNodeCentered(node, { scale, canvasWidth: PRINTABLE_DOTS })
          const base64 = dataUrl.replace(/^data:image\/[a-z]+;base64,/, '')
          const p = typeof window !== 'undefined' && window.Capacitor?.Plugins?.SunmiPrinter
          if (!p) throw new Error('KHONG thay SunmiPrinter')
          await p.printBitmap({ bitmap: base64 })
          await p.lineWrap({ lines: 3 })
          await p.cutPaper()
        } catch {
          /* nuốt lỗi in — không chặn UI; finishNativeJob ở finally */
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

  // Chỉ render node khi có job hợp lệ (data thật). Off-screen, hiển thị THẬT (không display:none).
  if (!job || !SUPPORTED.has(job.mode) || !_hasData(job)) return null
  return (
    <div
      ref={nodeRef}
      aria-hidden="true"
      style={{ position: 'fixed', left: -9999, top: 0, width: `${BILL_WIDTH_MM}mm`, background: '#fff' }}
    >
      {job.mode === 'shift' ? (
        <ShiftSlipBody kind={job.kind} shift={job.shift} branchName={job.branchName} />
      ) : job.mode === 'lien2' ? (
        <Lien2LabelBody order={job.order} seq={job.seq || null} widthMm={LABEL_WIDTH_MM} />
      ) : (
        <BillContent qrRenderer="canvas" order={job.order} config={job.config} />
      )}
    </div>
  )
}
