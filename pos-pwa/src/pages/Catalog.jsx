import { useMemo } from 'react'
import { useSearchParams } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import BranchServiceVisibility from './BranchServiceVisibility'
import CategoriesManage from './CategoriesManage'
import PriceRulesManage from './PriceRulesManage'
import ServicesManage from './ServicesManage'

// Hub "Dịch vụ & bảng giá" — gom 4 màn quản lý vào 1 (tab). Tab theo ?tab= (deep-link),
// lọc theo role: owner 4 tab; manager 2 (Danh mục + Dịch vụ & bảng giá). THUẦN vỏ —
// logic/CRUD/API/RLS của từng màn con giữ nguyên.
const TABS = [
  { key: 'categories', label: 'Danh mục', roles: ['owner', 'manager'], C: CategoriesManage },
  { key: 'services', label: 'Dịch vụ & bảng giá', roles: ['owner', 'manager'], C: ServicesManage },
  { key: 'price-rules', label: 'Phụ thu & giảm giá', roles: ['owner'], C: PriceRulesManage },
  { key: 'visibility', label: 'Hiển thị theo CN', roles: ['owner'], C: BranchServiceVisibility },
]

export default function Catalog() {
  const { user } = useAuth()
  const [params, setParams] = useSearchParams()

  const allowed = useMemo(
    () => TABS.filter((t) => t.roles.includes(user?.role)),
    [user?.role],
  )
  // Tab yêu cầu (?tab=) nếu hợp quyền; không thì fallback tab đầu được phép.
  const active = allowed.find((t) => t.key === params.get('tab')) || allowed[0]

  if (!active) {
    return <p className="shift__hint">Bạn không có quyền xem mục này.</p>
  }
  const ActiveScreen = active.C

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Dịch vụ &amp; bảng giá</h2>
      </div>

      <div className="seg" style={{ marginBottom: 14 }}>
        {allowed.map((t) => (
          <button
            key={t.key}
            type="button"
            className={`seg__btn ${active.key === t.key ? 'seg__btn--active' : ''}`}
            onClick={() => setParams({ tab: t.key }, { replace: true })}
          >
            {t.label}
          </button>
        ))}
      </div>

      <ActiveScreen />
    </div>
  )
}
