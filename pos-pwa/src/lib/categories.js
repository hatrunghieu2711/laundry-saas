// Helper danh mục dịch vụ (categories) — Stage 4.3.

// Bộ icon gợi ý cho danh mục (emoji — gọn, không cần asset). Owner chọn 1 trong số này
// hoặc dán emoji bất kỳ. Liên quan giặt ủi.
export const CATEGORY_ICONS = [
  '🧺', '👕', '👔', '👖', '🧥', '🧦', '🩳', '👗', '🥼', '🧣',
  '🛏️', '🪟', '🧸', '👟', '🎽', '🧴', '🫧', '♨️', '⭐', '📦',
]

export const DEFAULT_CATEGORY_ICON = '🧺'

// Chuẩn hoá category từ API.
export function normalizeCategory(c) {
  return {
    id: c.id,
    name: c.name,
    icon: c.icon || null,
    display_order: c.display_order ?? 0,
    is_active: c.is_active !== false,
  }
}
