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
export function normalizeService(s) {
  return {
    ...s,
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
