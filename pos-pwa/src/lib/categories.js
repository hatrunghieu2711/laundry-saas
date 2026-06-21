// Helper danh mục dịch vụ (categories) — Stage 4.3.
// (CATEGORY_ICONS/DEFAULT_CATEGORY_ICON đã gỡ — danh mục bỏ emoji, hiển thị bằng tên.)

// Chuẩn hoá category từ API. (icon vẫn map từ API để không phá nếu BE còn trả; FE không hiển thị.)
export function normalizeCategory(c) {
  return {
    id: c.id,
    name: c.name,
    icon: c.icon || null,
    display_order: c.display_order ?? 0,
    is_active: c.is_active !== false,
  }
}
