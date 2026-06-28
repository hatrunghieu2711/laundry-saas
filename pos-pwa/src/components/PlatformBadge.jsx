import { getPrintChannel } from '../lib/platform'

// ⚠️ TẠM (test môi trường) — GỠ sau khi xác nhận native vs web trên máy thật.
// Hiện kênh in sẽ dùng: "IN: native" (vỏ Capacitor) / "IN: web" (PWA/browser, gồm T1).
// position:fixed góc dưới phải, nền mờ, chữ nhỏ, z-index cao, pointer-events:none (không chặn
// thao tác). Nằm trong #root → @media print ẩn (#root display:none) nên KHÔNG in ra phiếu.
export default function PlatformBadge() {
  const channel = getPrintChannel()
  return (
    <div
      aria-hidden="true"
      style={{
        position: 'fixed',
        right: 6,
        bottom: 6,
        zIndex: 2147483647,
        padding: '2px 8px',
        borderRadius: 6,
        background: 'rgba(15, 23, 42, 0.72)',
        color: '#fff',
        font: '600 11px system-ui, -apple-system, sans-serif',
        letterSpacing: '0.02em',
        pointerEvents: 'none',
        userSelect: 'none',
      }}
    >
      IN: {channel}
    </div>
  )
}
