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
