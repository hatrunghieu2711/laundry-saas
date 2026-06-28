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
// ⚠️ FIX in liên 2 ra BILL trên T2 (window.print không chặn + afterprint KHÔNG bắn trên
// Sunmi): timeout cũ 1000ms → cleanup (xóa class print-job-lien2 + unmount nhãn) chạy KHI
// preview T2 còn mở → rơi về mặc định = BILL. Tăng 6000ms → cleanup hoãn tới khi user đã
// xong print dialog → nhãn giữ nguyên suốt preview. (BƯỚC XÁC NHẬN chẩn đoán; đủ → giữ.
// TRADE-OFF: máy KHÔNG bắn afterprint → in N nhãn chờ N×6s; afterprint có bắn → vẫn nhanh.)
export const PRINT_FALLBACK_MS = 6000

function setBodyMode(mode) {
  document.body.classList.remove('print-job-bill', 'print-job-lien2')
  if (mode) document.body.classList.add(`print-job-${mode}`)
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
      setBodyMode(null)
      setActive(null)
      const cb = doneCbRef.current
      doneCbRef.current = null
      if (cb) cb()
      return
    }
    idxRef.current = i
    setBodyMode(jobs[i].mode) // bật body class TRƯỚC khi in (ẩn job khác)
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
      setBodyMode(null)
    },
    [],
  )

  return { active, printing: active !== null, run }
}
