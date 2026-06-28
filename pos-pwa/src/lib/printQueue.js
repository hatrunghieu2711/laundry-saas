import { useCallback, useEffect, useRef, useState } from 'react'

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
// đột → kẹt driver. SỬA GỐC: chọn mảnh in bằng MOUNT/UNMOUNT DOM (T2 in cái gì CÓ trong
// DOM, không cần class). printMode: 'bill' | 'lien2' | null. Receipt (bill) UNMOUNT khi
// 'lien2' → T2 chỉ còn nhãn. printQueue set qua setPrintMode (mọi job).
let _printMode = null
const _modeSubs = new Set()
function setPrintMode(mode) {
  _printMode = mode
  _modeSubs.forEach((fn) => fn(mode))
}

export function usePrintMode() {
  const [mode, setMode] = useState(_printMode)
  useEffect(() => {
    _modeSubs.add(setMode)
    setMode(_printMode) // đồng bộ giá trị hiện tại khi mount
    return () => {
      _modeSubs.delete(setMode)
    }
  }, [])
  return mode
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
