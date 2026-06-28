import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from 'react'

// ── Hàng đợi IN TUẦN TỰ (Stage 6.9.4) ───────────────────────────────────────
// Mỗi MẢNH in (bill, từng nhãn liên 2) = MỘT window.print() RIÊNG. Máy nhiệt Sunmi
// CHỈ cắt giấy ở CUỐI mỗi print job (page-break KHÔNG phát lệnh cắt) → tách job =
// máy cắt rời từng mảnh.
//
// Điểm DỄ VỠ: Sunmi KHÔNG bắn 'afterprint' đáng tin → BẮT BUỘC fallback timeout.
// Cơ chế: cờ idxRef (đang in / job nào) chặn chồng job; mỗi job chờ xong bằng
// afterprint HOẶC timeout (chốt nào tới trước) rồi MỚI kéo job kế; token chống
// double-advance khi cả 2 cùng bắn.
export const PRINT_FALLBACK_MS = 2000 // 6000→2000: mount/unmount (printMode) là cơ chế chính, không cần dài

// ── MODE IN TOÀN CỤC — mount/unmount thay CSS body class (FIX T2) ─────────────
// ⚠️ T2 print engine KHÔNG áp body class set runtime trong @media print → cơ chế cũ
// (body.print-job-lien2 ẩn bill) VÔ HIỆU trên T2 → bill (mặc-định-hiện) rò + @page xung
// đột → kẹt driver. SỬA GỐC: chọn mảnh in bằng MOUNT/UNMOUNT DOM. printMode:
// 'bill' | 'lien2' | null. Receipt (bill) UNMOUNT khi 'lien2' → T2 chỉ còn nhãn.
//
// ⚠️ DÙNG useSyncExternalStore (KHÔNG useState+manual subs): khi Lien2PrintButton (component
// RIÊNG) set printMode='lien2', CHA của <Receipt> (OrderNew) KHÔNG re-render → useState+subs
// KHÔNG đảm bảo Receipt commit unmount TRƯỚC print() (race, T2 chậm lộ ra → bill+nhãn cùng
// DOM → ra BILL). useSyncExternalStore re-render ĐỒNG BỘ, tear-free → unmount chắc trước print.
let _printMode = null
const _modeSubs = new Set()

function _subscribePrintMode(cb) {
  _modeSubs.add(cb)
  return () => {
    _modeSubs.delete(cb)
  }
}
function _getPrintMode() {
  return _printMode
}

// ⚠️⚠️ DEBUG TẠM (v6 SÂU) — XÓA SAU. Log có timestamp (ms từ load) + console.log + overlay.
export const DEBUG_PRINT_BUILD = 'DBG-deep-v6' // marker: founder xác nhận đang chạy bundle MỚI
const _printDebugLog = []
const _t0 = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
function _ms() {
  const t = typeof performance !== 'undefined' && performance.now ? performance.now() : Date.now()
  return Math.round(t - _t0)
}
export function dbgLog(line) {
  const e = `+${_ms()}ms ${line}`
  _printDebugLog.push(e)
  if (_printDebugLog.length > 12) _printDebugLog.shift()
  if (typeof console !== 'undefined') console.log('[PRINTDBG]', e)
}
export function getPrintDebugLog() {
  return _printDebugLog
}
// Snapshot DOM THẬT lúc print(): đếm node + getComputedStyle(display) + offsetHeight → cái nào
// THỰC SỰ visible (display!=none & h>0) sẽ in. Đây là phép đo mấu chốt (không đoán).
function _dbgPrintSnapshot() {
  const fmt = (sel) => {
    const nodes = typeof document !== 'undefined' ? document.querySelectorAll(sel) : []
    const parts = Array.from(nodes).map((el) => {
      const cs = window.getComputedStyle(el)
      return `disp=${cs.display},h=${el.offsetHeight}`
    })
    return `[${nodes.length}]${parts.length ? ' ' + parts.join(' | ') : ''}`
  }
  dbgLog(`PRINT mode=${_printMode} receipt${fmt('.print-receipt')} lien2${fmt('.print-lien2')}`)
}

// Set mode TOÀN CỤC + notify (useSyncExternalStore tự gọi getSnapshot + re-render subscriber).
// Export để 5 đường in bill TRỰC TIẾP set 'bill' tường minh (tránh kẹt 'lien2' từ lần trước).
export function setPrintMode(mode) {
  if (_printMode === mode) return
  _printMode = mode
  dbgLog(`setPrintMode -> ${mode}`) // DEBUG TẠM
  _modeSubs.forEach((cb) => cb())
}

export function usePrintMode() {
  return useSyncExternalStore(_subscribePrintMode, _getPrintMode)
}

export function usePrintQueue() {
  const [active, setActive] = useState(null) // job đang in {mode, ...} | null
  const jobsRef = useRef([])
  const idxRef = useRef(-1)
  const tokenRef = useRef(0)
  const timerRef = useRef(null)
  const doneCbRef = useRef(null)

  const startAt = useCallback((i) => {
    const jobs = jobsRef.current
    if (i < 0 || i >= jobs.length) {
      // hết hàng đợi → dọn
      idxRef.current = -1
      jobsRef.current = []
      setPrintMode(null)
      setActive(null)
      const cb = doneCbRef.current
      doneCbRef.current = null
      if (cb) cb()
      return
    }
    idxRef.current = i
    setPrintMode(jobs[i].mode) // mode TOÀN CỤC TRƯỚC khi in → Receipt unmount khi 'lien2'
    setActive(jobs[i]) // re-render: component hiện nội dung job này vào vùng in
  }, [])

  // active đổi → nội dung job đã render → in + chờ xong (afterprint/timeout) → kế.
  useEffect(() => {
    if (!active) return undefined
    const token = ++tokenRef.current
    let finished = false
    const finish = () => {
      if (finished || token !== tokenRef.current) return // job này đã xong / cũ
      finished = true
      clearTimeout(timerRef.current)
      window.removeEventListener('afterprint', finish)
      startAt(idxRef.current + 1)
    }
    // chờ 2 frame: DOM job hiện tại + body class + style (rotate…) áp xong mới in
    let raf2 = 0
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        window.addEventListener('afterprint', finish)
        timerRef.current = setTimeout(finish, PRINT_FALLBACK_MS)
        _dbgPrintSnapshot() // ⚠️ DEBUG TẠM — đo DOM thật (node + display + h) NGAY trước window.print()
        window.print()
      })
    })
    return () => {
      cancelAnimationFrame(raf1)
      cancelAnimationFrame(raf2)
      clearTimeout(timerRef.current)
      window.removeEventListener('afterprint', finish)
    }
  }, [active, startAt])

  // run(jobs): bắt đầu hàng đợi. jobs = [{mode:'bill'} | {mode:'lien2', seq}].
  const run = useCallback(
    (jobs, onDone) => {
      if (idxRef.current !== -1) return false // đang in → không chồng
      if (!jobs || !jobs.length) return false
      jobsRef.current = jobs
      doneCbRef.current = onDone || null
      startAt(0)
      return true
    },
    [startAt],
  )

  useEffect(
    () => () => {
      clearTimeout(timerRef.current)
      setPrintMode(null)
    },
    [],
  )

  return { active, printing: active !== null, run }
}
