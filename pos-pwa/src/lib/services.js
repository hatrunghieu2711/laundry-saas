// Helper cho bảng giá dịch vụ động (services + tiers).
import { toNumber } from './format'

// Đơn vị dịch vụ (khớp enum backend: kg|cai|con|bo|luot).
export const UNITS = [
  { value: 'kg', label: 'Kg' },
  { value: 'cai', label: 'Cái' },
  { value: 'con', label: 'Con' },
  { value: 'bo', label: 'Bộ' },
  { value: 'luot', label: 'Lượt' },
]
export const UNIT_LABEL = Object.fromEntries(UNITS.map((u) => [u.value, u.label]))

// Chuẩn hoá field tiền (nợ kỹ thuật 5E+4 → Number) + sort tiers theo display_order.
// category là thực thể riêng (Stage 4.3): category_id + object category {id,name,icon}.
export function normalizeService(s) {
  return {
    ...s,
    category_id: s.category_id || null,
    category: s.category || null, // { id, name, icon, display_order } | null
    is_favorite: !!s.is_favorite,
    unit_price: toNumber(s.unit_price),
    tiers: (s.tiers || [])
      .map((t) => ({
        ...t,
        price: toNumber(t.price),
        max_value: t.max_value == null ? null : toNumber(t.max_value),
      }))
      .sort((a, b) => (a.display_order ?? 0) - (b.display_order ?? 0)),
  }
}
