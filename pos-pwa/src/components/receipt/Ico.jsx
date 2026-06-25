// Icon inline SVG (Stage 6.69) — thay glyph ✎⧉🗑↑↓⊞✓ (KHÔNG webfont/emoji).
// Tách ra shared (Stage refactor editor) — BlockListEditor + ReceiptSettings dùng chung.
const RICONS = {
  edit: 'M4 20h3.5L17 9.5a2.1 2.1 0 0 0-3-3L3.5 17z M12.5 8l3 3',
  copy: 'M9 9h9v9H9z M5 14V6a1 1 0 0 1 1-1h8',
  trash: 'M4 7h16 M9 7V5h6v2 M6 7l1 13h10l1-13 M10 11v5 M14 11v5',
  up: 'M12 19V6 M6 12l6-6 6 6',
  down: 'M12 5v13 M6 12l6 6 6-6',
  merge: 'M5 5h6v6H5z M13 13h6v6h-6z M11 8h5v5',
  check: 'M20 6L9 17l-5-5',
}

export default function Ico({ name }) {
  return (
    <svg className="ic-btn" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={RICONS[name]} />
    </svg>
  )
}
