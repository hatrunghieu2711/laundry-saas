import { useSyncExternalStore } from 'react'

// ⚠️ TẠM (chẩn đoán native print) — log DÙNG CHUNG cho mọi module (printQueue/OrderNew/
// NativePrintLayer) → hiện trên vùng debug của PlatformBadge (T2 khó xem console). GỠ cùng debug.
const _lines = []
let _version = 0
const _subs = new Set()

export function dbg(line) {
  _lines.push(line)
  if (_lines.length > 60) _lines.shift()
  _version += 1
  _subs.forEach((cb) => cb())
  if (typeof console !== 'undefined') console.log('[DBG]', line)
}

export function getDebugLog() {
  return _lines
}

function _subscribe(cb) {
  _subs.add(cb)
  return () => _subs.delete(cb)
}
function _getVersion() {
  return _version
}

// Hook để component re-render mỗi khi có dbg() (snapshot = version số → tear-free).
export function useDebugVersion() {
  return useSyncExternalStore(_subscribe, _getVersion)
}
