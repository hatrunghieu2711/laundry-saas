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

// CỜ IN NATIVE — BẬT (production): mọi máy isNativePlatform()===true (T2-APK Capacitor) in native
// printBitmap mặc định. T1 (PWA Chrome, KHÔNG trong Capacitor) → isNativePlatform()===false →
// nativePrintActive()===false → VẪN window.print (KHÔNG đổi).
export const NATIVE_PRINT_ENABLED = true;

// In native CÓ đang bật không: phải đang chạy native (vỏ Capacitor) — ngược lại (T1/PWA/browser) →
// FALSE → window.print y nguyên. Trong native: override runtime THẮNG cờ build (cả 2 chiều) →
//   ?nativeprint=1 / localStorage.nativeprint='1' → ÉP native;
//   ?nativeprint=0 / localStorage.nativeprint='0' → ÉP web (TẮT KHẨN CẤP, kể cả khi cờ=true);
//   không có override → theo NATIVE_PRINT_ENABLED (production = true).
export function nativePrintActive() {
  if (!isNativePlatform()) return false;
  try {
    if (typeof window !== 'undefined') {
      const q = new URLSearchParams(window.location.search).get('nativeprint');
      if (q === '1') return true;
      if (q === '0') return false;
      const ls = window.localStorage ? window.localStorage.getItem('nativeprint') : null;
      if (ls === '1') return true;
      if (ls === '0') return false;
    }
  } catch {
    /* noop */
  }
  return NATIVE_PRINT_ENABLED;
}
