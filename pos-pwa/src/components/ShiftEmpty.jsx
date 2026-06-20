// Empty-state "chưa có ca" DÙNG CHUNG (Stage 6.58) — vỏ + icon đồng hồ INLINE SVG (KHÔNG
// emoji/webfont). Body (text + nút + form) do từng màn truyền qua children. Sửa 1 chỗ → cả 4
// màn (Shift / OrderNew / OrderPay / CashBook) theo. Style chuẩn mới: .shift__empty radius 12 +
// border 1px var(--line), KHÔNG box-shadow (khối lớn — an toàn Chrome 56). CSS ở index.css.
export default function ShiftEmpty({ children }) {
  return (
    <div className="shift__empty">
      <svg
        className="shift__empty-icon"
        viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.6"
        strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"
      >
        <circle cx="12" cy="12" r="9" />
        <path d="M12 7.5V12l3 1.8" />
      </svg>
      {children}
    </div>
  )
}
