/* global __APP_VERSION__ */
import { useState } from 'react'
import { tenantTrackBase } from '../lib/track'

// Phiên bản app (Vite define từ package.json). Fallback '' khi chạy ngoài build.
const APP_VERSION = typeof __APP_VERSION__ !== 'undefined' ? __APP_VERSION__ : ''

// Badge hạn gói theo subscription_status (active xanh lá · warning vàng · grace cam ·
// expired đỏ) — khớp banner Layout + panel AdminTenantDetail.
const EXPIRY = {
  active: { label: 'Còn hạn', bg: '#e3f6e8', color: '#16794a' },
  warning: { label: 'Sắp hết hạn', bg: '#fef9c3', color: '#854d0e' },
  grace: { label: 'Ân hạn', bg: '#ffedd5', color: '#9a3412' },
  expired: { label: 'Đã hết hạn', bg: '#fde8e8', color: '#b42318' },
}

// Hạn lưu dạng UTC-midnight → cắt 10 ký tự đầu lấy ngày (round-trip đúng mọi múi giờ).
const fmtDate = (iso) => (iso ? iso.slice(0, 10) : '')

// Panel "Thông tin tiệm" (CHỈ owner — Layout gác role). Dữ liệu từ /auth/me.
export default function TenantInfoModal({ user, onClose, onLogout }) {
  const [copied, setCopied] = useState(false)
  const slug = user?.tenant_slug || ''
  const trackLink = tenantTrackBase(slug)
  const tel = (user?.support_contact || '').replace(/\s+/g, '') // tel: bỏ khoảng trắng
  const ex = EXPIRY[user?.subscription_status] || EXPIRY.active

  const copyLink = async () => {
    try {
      await navigator.clipboard.writeText(trackLink)
      setCopied(true)
      setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard không khả dụng — bỏ qua */
    }
  }

  return (
    <div
      className="modal-overlay modal-overlay--top"
      role="dialog"
      aria-modal="true"
      onClick={onClose}
    >
      {/* stopPropagation: bấm trong panel KHÔNG đóng; bấm nền ngoài thì đóng. */}
      <div className="panel panel--modal" onClick={(e) => e.stopPropagation()}>
        <div className="panel__head">
          <span className="panel__title">{user?.tenant_name || 'Cửa hàng'}</span>
          <button className="btn btn--ghost btn--sm" style={{ marginLeft: 'auto' }} onClick={onClose}>
            Đóng
          </button>
        </div>

        <div className="panel__body">
          {/* Cửa hàng */}
          <div className="panel__group">
            <div className="panel__row"><span>Vai trò</span><b>{user?.role_label || user?.role || '—'}</b></div>
            <div className="panel__row"><span>Mã cửa hàng</span><b>{slug || '—'}</b></div>
          </div>

          {/* Gói dịch vụ */}
          <div className="panel__group">
            <div className="panel__row panel__row--strong"><span>Gói dịch vụ</span><b>{user?.plan_name || '—'}</b></div>
            <div className="panel__row">
              <span>Chi nhánh</span>
              <b>{user?.branch_count ?? '—'} / {user?.branch_max ?? '—'}</b>
            </div>
            <div className="panel__row">
              <span>Thời hạn</span>
              <span style={{ display: 'inline-flex', alignItems: 'center' }}>
                <b style={{ marginRight: 6 }}>
                  {user?.subscription_expires_at ? fmtDate(user.subscription_expires_at) : 'Vô hạn'}
                </b>
                <span style={{ fontSize: 12, fontWeight: 600, padding: '1px 8px', borderRadius: 999, background: ex.bg, color: ex.color }}>
                  {ex.label}
                </span>
              </span>
            </div>
            {tel && (
              <a className="btn btn--primary btn--block" href={`tel:${tel}`}>Liên hệ gia hạn</a>
            )}
          </div>

          {/* Tra cứu */}
          <div className="panel__group">
            <div className="panel__row"><span>Link tra cứu của tiệm</span></div>
            <div style={{ display: 'flex', alignItems: 'center' }}>
              <input
                className="input" readOnly value={trackLink} style={{ flex: 1 }}
                onFocus={(e) => e.target.select()}
              />
              <button className="btn btn--ghost btn--sm" style={{ marginLeft: 8 }} onClick={copyLink}>
                {copied ? 'Đã chép' : 'Copy'}
              </button>
            </div>
          </div>

          {/* Hỗ trợ + phiên bản */}
          <div className="panel__group">
            <div className="panel__row">
              <span>Hỗ trợ</span>
              {tel ? <a href={`tel:${tel}`}><b>{user.support_contact}</b></a> : <b>—</b>}
            </div>
            <div className="panel__row"><span>Phiên bản</span><b>{APP_VERSION || '—'}</b></div>
          </div>
        </div>

        <div className="panel__foot">
          <button className="btn btn--danger" onClick={onLogout}>Đăng xuất</button>
        </div>
      </div>
    </div>
  )
}
