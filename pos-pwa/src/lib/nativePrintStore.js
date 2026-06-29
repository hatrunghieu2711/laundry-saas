import { useSyncExternalStore } from 'react'
import { getReceiptConfig } from './receipt'

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
  if (_busy || _current) return false // đang in → bỏ qua bấm dồn (không chồng/kẹt)
  _busy = true
  try {
    const cfg = config || (await getReceiptConfig())
    await runNativeJob({ mode: 'bill', order, config: cfg })
  } catch {
    /* nuốt lỗi — không chặn UI; NativePrintLayer luôn finishNativeJob */
  } finally {
    _busy = false
  }
  return true
}

// Helper IN PHIẾU GIAO CA NATIVE TRỰC TIẾP (Shift, ngoài queue). kind 'handover'|'report' + shift
// (đã đóng) + branchName. Guard _busy như nativePrintBill. NativePrintLayer mode='shift' → ShiftSlipBody.
export async function nativePrintShift(kind, shift, branchName) {
  if (!kind || !shift) return false
  if (_busy || _current) return false // đang in → bỏ qua bấm dồn
  _busy = true
  try {
    await runNativeJob({ mode: 'shift', kind, shift, branchName })
  } catch {
    /* nuốt lỗi — không chặn UI */
  } finally {
    _busy = false
  }
  return true
}
