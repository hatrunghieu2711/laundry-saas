// Phát hiện môi trường chạy: app native (vỏ Capacitor) hay browser/PWA thường.
// KHÔNG cần dependency @capacitor/core — Capacitor inject window.Capacitor sẵn trong WebView.

export function isNativePlatform() {
  if (typeof window === 'undefined') return false;
  const cap = window.Capacitor;
  if (!cap) return false;
  // isNativePlatform() có ở Capacitor 3+; fallback về sự tồn tại của window.Capacitor
  if (typeof cap.isNativePlatform === 'function') return cap.isNativePlatform();
  return true;
}

// Kênh in sẽ dùng. Giai đoạn này chỉ trả nhãn để test; logic in thật thêm ở GĐ sau.
// 'native'  = in qua ESC/POS (máy trong vỏ Capacitor)
// 'web'     = in qua window.print() (PWA/browser, gồm T1)
export function getPrintChannel() {
  return isNativePlatform() ? 'native' : 'web';
}

// ⚠️ CỜ IN NATIVE — MẶC ĐỊNH TẮT. Bật (sửa true + rebuild) khi đã test in native printBitmap ổn.
export const NATIVE_PRINT_ENABLED = false;

// In native CÓ đang bật không: phải đang chạy native (vỏ Capacitor) VÀ (cờ build bật HOẶC override
// runtime ?nativeprint=1 / localStorage.nativeprint==='1'). Mặc định FALSE → T1/PWA/browser, và T2
// khi CHƯA bật cờ → tất cả GIỮ window.print y nguyên (không đổi hành vi).
export function nativePrintActive() {
  if (!isNativePlatform()) return false;
  if (NATIVE_PRINT_ENABLED) return true;
  try {
    if (typeof window !== 'undefined') {
      if (new URLSearchParams(window.location.search).get('nativeprint') === '1') return true;
      if (window.localStorage && window.localStorage.getItem('nativeprint') === '1') return true;
    }
  } catch {
    /* noop */
  }
  return false;
}
