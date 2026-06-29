import { useSyncExternalStore } from 'react'
import { getReceiptConfig } from './receipt'
import { dbg } from './debugLog' // ⚠️ TẠM — log chẩn đoán

// Store nhỏ điều phối IN NATIVE (printBitmap). usePrintQueue đẩy 1 job → <NativePrintLayer> nghe
// store, render node bill off-screen + chụp + printBitmap + cutPaper → finishNativeJob() → Promise
// của runNativeJob() resolve → queue sang job kế (await TUẦN TỰ, KHÔNG afterprint/window.print).
// Mỗi job native = { mode:'bill'|'lien2', order, config, seq }.
let _current = null // { job, resolve } | null
let _busy = false // ⚠️ chống bấm DỒN từ nút in TRỰC TIẾP (ngoài queue) → 1 job/lần, không chồng/kẹt
const _subs = new Set()

function _notify() {
  _subs.forEach((cb) => cb())
}

// Queue gọi: await runNativeJob(job). Promise resolve khi NativePrintLayer in xong (finishNativeJob).
export function runNativeJob(job) {
  return new Promise((resolve) => {
    if (_current) {
      // đang có job (KHÔNG nên xảy ra vì queue tuần tự) → giải phóng cũ để không kẹt
      const prev = _current
      _current = null
      prev.resolve()
    }
    _current = { job, resolve }
    _notify()
  })
}

// NativePrintLayer gọi khi in XONG (hoặc lỗi) → resolve promise + clear current (LUÔN gọi để
// không kẹt hàng đợi).
export function finishNativeJob() {
  const cur = _current
  _current = null
  _notify()
  if (cur) cur.resolve()
}

function _subscribe(cb) {
  _subs.add(cb)
  return () => _subs.delete(cb)
}
function _getCurrentJob() {
  return _current ? _current.job : null
}

export function useCurrentNativeJob() {
  return useSyncExternalStore(_subscribe, _getCurrentJob)
}

// Đang in native (job trong store hoặc helper đang chạy)?
export function isNativeBusy() {
  return _busy || _current != null
}

// Helper IN BILL NATIVE TRỰC TIẾP (4 nút "In lại bill" ngoài queue: History/OrderPay/OrderDetail/
// Board). order BẮT BUỘC; config thiếu → getReceiptConfig() (cache, nhanh). _busy đặt ĐỒNG BỘ ở
// đầu → bấm DỒN khi đang in → BỎ QUA (không chồng job, không kẹt). nativePrintActive caller tự kiểm.
export async function nativePrintBill(order, config) {
  if (!order) return false
  if (_busy || _current) {
    dbg('nativePrintBill: dang in → bo qua click')
    return false
  }
  _busy = true
  try {
    const cfg = config || (await getReceiptConfig())
    await runNativeJob({ mode: 'bill', order, config: cfg })
  } catch (e) {
    dbg('nativePrintBill loi: ' + (e && e.message ? e.message : String(e)))
  } finally {
    _busy = false
  }
  return true
}
