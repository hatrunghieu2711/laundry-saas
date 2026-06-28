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

// ⚠️⚠️ DEBUG TẠM (v7 SÂU) — XÓA SAU. Log có timestamp (ms từ load) + console.log + overlay.
export const DEBUG_PRINT_BUILD = 'DBG-reload-v10' // marker: founder xác nhận đang chạy bundle MỚI (reload sau in + gộp nhãn)
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

// ── ⚠️⚠️ DEBUG TẠM (việc 1): BẮT LỖI JS TOÀN CỤC → log overlay ────────────────
// Nếu in lần 2 CRASH mà overlay KHÔNG có dòng ERR/REJECT nào → crash THUẦN NATIVE
// (SunmiPrinter là process Android riêng, KHÔNG ném vào JS) → củng cố: không sửa được
// bằng JS thuần, PHẢI đổi KÊNH IN (Sunmi JS bridge / native). Có dòng ERR → lỗi JS thật.
let _errCaptureInstalled = false
function _installGlobalErrorCapture() {
  if (_errCaptureInstalled || typeof window === 'undefined') return
  _errCaptureInstalled = true
  window.addEventListener('error', (e) => {
    const m = e && e.error ? (e.error.stack || e.error.message) : `${e && e.message} @${e && e.filename}:${e && e.lineno}`
    dbgLog(`ERR ${String(m).slice(0, 220)}`)
  })
  window.addEventListener('unhandledrejection', (e) => {
    const r = e && e.reason
    const m = r && (r.stack || r.message) ? r.stack || r.message : String(r)
    dbgLog(`REJECT ${String(m).slice(0, 220)}`)
  })
  dbgLog('errCapture ON')
}

// ── ⚠️⚠️ DEBUG TẠM (việc 2): DÒ SUNMI JS BRIDGE trong runtime ─────────────────
// Tìm KÊNH IN NATIVE qua JS (KHÔNG qua Android print framework = cái đang crash). Sunmi CÓ
// "Web Print JS SDK" expose hàm window.printText/printBitmap/printQrCode/sendEscCommand… NHƯNG
// chỉ khi WebView host (app Sunmi / WebView có addJavascriptInterface) inject bridge. PWA mở
// Chrome thuần → thường KHÔNG có. Probe này CHỐT: runtime của founder CÓ bridge không?
//   - SDK-fns=[printText,…] có hàm → DÙNG ĐƯỢC SDK (fix đúng: in qua bridge, bỏ window.print()).
//   - keys=∅ & SDK-fns=∅ → không bridge → chỉ còn window.print() (crash) → cần SDK script / wrap native.
export function probeSunmiBridge() {
  if (typeof window === 'undefined') return
  try {
    const re = /sunmi|print|android|webview|innerprinter|woyou|escpos/i
    const keys = Object.keys(window).filter((k) => re.test(k))
    dbgLog(`BRIDGE keys=[${keys.slice(0, 25).join(',') || '∅'}]`)
    const objs = ['sunmi', 'SunmiPrinter', 'sunmiPrinter', 'WebPrint', 'Android', 'innerPrinter', 'InnerPrinter', 'woyou', 'SunmiPrintService', 'WebViewJavascriptBridge']
    objs.forEach((name) => {
      const v = window[name]
      if (v == null) return
      let info = typeof v
      try {
        if (typeof v === 'object') info += ` keys=[${Object.keys(v).slice(0, 20).join(',')}]`
      } catch {
        /* noop */
      }
      dbgLog(`BRIDGE ${name}: ${info}`)
    })
    const fns = ['printText', 'printTexts', 'printBitmap', 'printQrCode', 'printBarCode', 'sendEscCommand', 'sendTsplCommand', 'initLine', 'addText', 'printDividingLine', 'enterPrinterBuffer', 'commitPrinterBuffer']
    const present = fns.filter((f) => typeof window[f] === 'function')
    dbgLog(`BRIDGE SDK-fns=[${present.join(',') || '∅'}]`)
    try {
      const nav = Object.keys(navigator).filter((k) => re.test(k))
      if (nav.length) dbgLog(`BRIDGE nav=[${nav.join(',')}]`)
    } catch {
      /* noop */
    }
    dbgLog(`BRIDGE UA=${String(navigator.userAgent || '').slice(0, 120)}`)
  } catch (e) {
    dbgLog(`BRIDGE probe lỗi: ${e && e.message ? e.message : e}`)
  }
}

_installGlobalErrorCapture()
probeSunmiBridge() // dò 1 lần lúc load; founder bấm "DÒ BRIDGE" trên overlay để dò lại sau khi WebView sẵn sàng
// Snapshot DOM THẬT lúc print(): mỗi node → display + offset w/h + textContent + số con DOM.
// ⚠️ Chạy KHI CÒN TRÊN MÀN (ngay trước window.print()), lúc này .print-lien2 ĐANG display:none
// (rule nền — chỉ display:block trong @media print). HỆ QUẢ ĐO:
//   - w/h = offsetWidth/Height = 0 vì đang ẩn → KHÔNG phải tín hiệu (đừng kết luận "rỗng" từ h=0).
//   - txt = textContent (BỎ khoảng trắng) — KHÔNG phụ thuộc layout → ĐỌC ĐƯỢC dù đang ẩn. Đây là
//     tín hiệu THẬT cho "nhãn CÓ chữ chưa". (Cố ý KHÔNG dùng innerText: innerText layout-aware →
//     trả '' cho phần tử ẩn → luôn 0 → đánh lừa thành "rỗng".)
//   - ch = childElementCount — số con DOM, cũng không phụ thuộc layout.
// → txt>0 & ch>0 = nhãn ĐÃ render nội dung vào DOM → trang trống khi in T2 là lỗi PRINT/driver,
//   KHÔNG phải render rỗng/thiếu data. txt=0 & ch=0 = nhãn render RỖNG (data/context sai).
function _dbgPrintSnapshot() {
  const fmt = (sel) => {
    const nodes = typeof document !== 'undefined' ? document.querySelectorAll(sel) : []
    const parts = Array.from(nodes).map((el) => {
      const cs = window.getComputedStyle(el)
      const txt = (el.textContent || '').replace(/\s+/g, '').length
      return `disp=${cs.display},w=${el.offsetWidth},h=${el.offsetHeight},txt=${txt},ch=${el.childElementCount}`
    })
    return `[${nodes.length}]${parts.length ? ' ' + parts.join(' | ') : ''}`
  }
  dbgLog(
    `PRINT mode=${_printMode} receipt${fmt('.print-receipt')} lien2${fmt('.print-lien2')} lbl${fmt('.print-lien2 .lbl')}`,
  )
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

// ── IN QUA IFRAME RIÊNG MỖI JOB (FIX GỐC T2) ─────────────────────────────────
// PHÉP THỬ xác nhận: window.print() TRANG CHÍNH lần 2+ trong CÙNG phiên → T2 WebView
// KHÔNG giải phóng print service → crash SunmiPrinter (đơn 1 OK, đơn 2 crash, reload OK
// lại). GIẢI GỐC: mỗi job in vào IFRAME MỚI (browsing context + document MỚI) → print
// context SẠCH mỗi lần, mô phỏng "reload". Giữ NGUYÊN render (Receipt/Lien2Layer/ShiftSlip
// portal) + CSS @media print/@page; CHỈ thay window.print() trang chính bằng iframe.print().
//
// CSS vào iframe: serialize ĐỒNG BỘ mọi stylesheet same-origin (app chỉ 1 file /assets) →
// 1 <style> (KHÔNG refetch <link> async → in ra ĐÃ đủ style). try/catch phòng sheet cross-
// origin (đọc cssRules ném SecurityError). Đã gồm @page billpg + @media print. Thêm 1 <style>
// ÉP .print-receipt/.print-lien2 display:block (iframe không có #root nên không dính
// @media-gate của trang chính; ép cho chắc + để <img> logo trong subtree được layout/load).
function _serializeAppCss() {
  const sheets = typeof document !== 'undefined' ? Array.from(document.styleSheets) : []
  return sheets
    .flatMap((ss) => {
      try {
        return Array.from(ss.cssRules).map((r) => r.cssText)
      } catch {
        return [] // sheet cross-origin → bỏ qua (app không có)
      }
    })
    .join('\n')
}

// printViaIframe(selector): clone mảnh đang render (.print-receipt | .print-lien2) sang iframe
// ẩn rồi in iframe. Promise resolve SAU khi in + xóa iframe (timeout) → queue dùng để kéo job
// kế (tuần tự, mỗi job 1 print context sạch). KHÔNG dựa afterprint (T2 không bắn tin cậy).
export function printViaIframe(selector) {
  return new Promise((resolve) => {
    const node = typeof document !== 'undefined' ? document.querySelector(selector) : null
    if (!node) {
      dbgLog(`printViaIframe: KHÔNG thấy ${selector} → bỏ qua`)
      resolve()
      return
    }
    const iframe = document.createElement('iframe')
    iframe.setAttribute('aria-hidden', 'true')
    iframe.style.cssText =
      'position:fixed;left:-9999px;top:0;width:80mm;height:0;border:0;opacity:0;pointer-events:none;'
    document.body.appendChild(iframe)

    let done = false
    const cleanup = () => {
      if (done) return
      done = true
      try {
        iframe.remove()
      } catch {
        /* noop */
      }
      resolve()
    }

    const doc = iframe.contentWindow.document
    doc.open()
    doc.write(
      '<!doctype html><html><head><meta charset="utf-8"><style>' +
        _serializeAppCss() +
        '</style><style>.print-receipt,.print-lien2{display:block!important}</style></head><body>' +
        node.outerHTML +
        '</body></html>',
    )
    doc.close()

    const fire = () => {
      dbgLog(`printViaIframe FIRE ${selector}`) // ⚠️ DEBUG TẠM
      try {
        iframe.contentWindow.focus()
        iframe.contentWindow.print()
      } catch (e) {
        dbgLog(`printViaIframe print() lỗi: ${e && e.message ? e.message : e}`)
      }
      // T2 không bắn afterprint tin cậy → xóa iframe + resolve bằng TIMEOUT (đừng xóa sớm hủy job)
      setTimeout(cleanup, PRINT_FALLBACK_MS)
    }

    // Chờ <img> (logo bill) load xong rồi mới in — tránh in trước khi logo về. Nhãn/bill-không-
    // logo: 0 img → in ngay (1-2 frame cho layout). QR là <svg> inline (đồng bộ) → không chờ.
    const imgs = Array.from(doc.images || [])
    const pending = imgs.filter((im) => !im.complete)
    dbgLog(`printViaIframe ${selector} imgs=${imgs.length} wait=${pending.length}`) // ⚠️ DEBUG TẠM
    if (pending.length) {
      let left = pending.length
      let fired = false
      const go = () => {
        if (fired) return
        fired = true
        requestAnimationFrame(fire)
      }
      pending.forEach((im) => {
        const oneDone = () => {
          left -= 1
          if (left <= 0) go()
        }
        im.addEventListener('load', oneDone)
        im.addEventListener('error', oneDone)
      })
      setTimeout(go, 1500) // logo chậm/không về → vẫn in sau 1.5s (không kẹt vô hạn)
    } else {
      requestAnimationFrame(() => requestAnimationFrame(fire))
    }
  })
}

// ── FULL RELOAD SAU IN (FIX GỐC T2) ──────────────────────────────────────────
// Gốc: print() lần 2+ trong CÙNG document → T2 crash (print service theo document). GIẢI:
// mỗi document chỉ in ĐÚNG 1 print() rồi FULL reload → document kế là "print lần 1" → không
// crash. PHẢI location.reload() (load document MỚI, reset print service); SPA navigate KHÔNG
// reset (cùng document). Print đã dispatch xong từ trước (printViaIframe fire print ~ngay,
// service nhận job ở process riêng) → reload sau delay an toàn, không cắt job.
export function reloadAfterPrint(delayMs = 1800) {
  if (typeof window === 'undefined') return
  try {
    const el = document.createElement('div')
    el.textContent = 'Đã in — đang làm mới…'
    el.setAttribute('aria-live', 'polite')
    el.style.cssText =
      'position:fixed;inset:0;z-index:2147483647;display:flex;align-items:center;justify-content:center;' +
      'background:rgba(255,255,255,0.94);color:#0f172a;font:600 16px system-ui,-apple-system,sans-serif;'
    document.body.appendChild(el)
  } catch {
    /* noop */
  }
  setTimeout(() => {
    try {
      window.location.reload()
    } catch {
      /* noop */
    }
  }, delayMs)
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

  // active đổi → mảnh job đã render (portal) → IN MẢNH ĐÓ QUA IFRAME RIÊNG (FIX T2: mỗi job =
  // print context SẠCH → window.print() lần 2+ không còn crash). Khi iframe in xong + tự xóa
  // (printViaIframe resolve) → kéo job kế. KHÔNG dựa afterprint trang chính (T2 không bắn tin cậy).
  useEffect(() => {
    if (!active) return undefined
    const token = ++tokenRef.current
    let cancelled = false
    let raf2 = 0
    const selector = active.mode === 'lien2' ? '.print-lien2' : '.print-receipt'
    // chờ 2 frame: mảnh job hiện tại mount (portal) + style áp xong rồi mới clone sang iframe
    const raf1 = requestAnimationFrame(() => {
      raf2 = requestAnimationFrame(() => {
        if (cancelled || token !== tokenRef.current) return
        _dbgPrintSnapshot() // ⚠️ DEBUG TẠM — đo DOM thật (node + display + h) NGAY trước khi clone sang iframe
        printViaIframe(selector).then(() => {
          if (cancelled || token !== tokenRef.current) return
          startAt(idxRef.current + 1)
        })
      })
    })
    return () => {
      cancelled = true
      cancelAnimationFrame(raf1)
      cancelAnimationFrame(raf2)
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
