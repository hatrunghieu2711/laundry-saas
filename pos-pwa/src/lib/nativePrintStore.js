import { useSyncExternalStore } from 'react'

// Store nhỏ điều phối IN NATIVE (printBitmap). usePrintQueue đẩy 1 job → <NativePrintLayer> nghe
// store, render node bill off-screen + chụp + printBitmap + cutPaper → finishNativeJob() → Promise
// của runNativeJob() resolve → queue sang job kế (await TUẦN TỰ, KHÔNG afterprint/window.print).
// Mỗi job native = { mode:'bill', order, config }.
let _current = null // { job, resolve } | null
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
