import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import BillContent from '../components/Bill'
import { ApiError, api } from '../lib/api'
import { clearReceiptCache, normalizeReceipt } from '../lib/receipt'

// Dữ liệu mẫu để preview song ngữ (đúng khổ 80mm, không gọi backend).
const SAMPLE_ORDER = {
  order_code: 'B1-00042',
  total_amount: 185000,
  pickup_at: '2026-06-14T03:30:00Z', // 10:30 14/06 (giờ VN)
  created_at: '2026-06-13T09:15:00Z', // 16:15 13/06 (giờ VN)
  customer_name: 'Chị Lan',
  customer_phone: '0905 123 456',
  items: [
    { id: 1, service_name: 'Giặt sấy (≤3kg)', quantity: 1, unit_price: 60000, subtotal: 60000 },
    { id: 2, service_name: 'Áo Vest', quantity: 2, unit_price: 60000, subtotal: 120000 },
    { id: 3, service_name: 'Giặt thường', quantity: 1, unit_price: 5000, subtotal: 5000 },
  ],
}

// Các trường text song ngữ chân phiếu (label cố định, owner sửa giá trị).
const FOOTER_FIELDS = [
  { key: 'hotline', label: 'Hotline' },
  { key: 'web', label: 'Web' },
  { key: 'address', label: 'Địa chỉ / Add' },
  { key: 'zalo_wa_kakao', label: 'Zalo / WhatsApp / Kakao' },
  { key: 'open_hours', label: 'Giờ mở cửa / OPEN' },
  { key: 'footer_text', label: 'Dòng cảm ơn (chân phiếu)' },
]

export default function ReceiptSettings() {
  const { user } = useAuth()
  const canEdit = user?.role === 'owner'

  const [cfg, setCfg] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  useEffect(() => {
    api
      .get('/settings/receipt')
      .then((c) => setCfg(normalizeReceipt(c)))
      .catch((e) => setError(e?.message || 'Không tải được cấu hình phiếu'))
  }, [])

  const set = (k, v) => {
    setSaved(false)
    setCfg((c) => ({ ...c, [k]: v }))
  }

  const onPickLogo = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    // Validate sớm ở client (server vẫn validate lại).
    if (!['image/png', 'image/jpeg', 'image/jpg'].includes(file.type)) {
      setError('Chỉ nhận ảnh PNG hoặc JPG.')
      if (fileRef.current) fileRef.current.value = ''
      return
    }
    if (file.size > 512 * 1024) {
      setError('Ảnh quá lớn (tối đa ~500KB).')
      if (fileRef.current) fileRef.current.value = ''
      return
    }
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const updated = await api.upload('/settings/receipt/logo', fd)
      clearReceiptCache()
      setCfg((c) => ({ ...normalizeReceipt(updated), ...c, logo_url: updated.logo_url }))
    } catch (err) {
      setError(
        err instanceof ApiError && err.status === 403
          ? 'Chỉ chủ chuỗi (owner) mới đổi được logo.'
          : err?.message || 'Tải logo thất bại',
      )
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await api.put('/settings/receipt', cfg)
      clearReceiptCache()
      setSaved(true)
    } catch (e) {
      setError(
        e instanceof ApiError && e.status === 403
          ? 'Chỉ chủ chuỗi (owner) mới lưu được mẫu phiếu.'
          : e?.message || 'Không lưu được cấu hình',
      )
    } finally {
      setSaving(false)
    }
  }

  // Preview dùng config hiện tại (đã chuẩn hoá đủ field).
  const preview = useMemo(() => (cfg ? normalizeReceipt(cfg) : null), [cfg])

  if (!cfg) {
    return <p className="shift__hint">{error || 'Đang tải cấu hình phiếu…'}</p>
  }

  return (
    <div className="rcfg">
      <div className="rcfg__editor">
        <h2 className="services__title">Mẫu phiếu in (song ngữ Việt / Anh)</h2>
        {!canEdit && (
          <div className="alert alert--error">Chỉ chủ chuỗi (owner) mới sửa được. Bạn đang xem.</div>
        )}

        {/* ── Logo & thương hiệu ─────────────────────────────────── */}
        <div className="card">
          <h3 className="card__title">Logo &amp; thương hiệu</h3>
          <div className="rcfg__logo">
            <div className="rcfg__logo-prev">
              {cfg.logo_url ? (
                <img src={cfg.logo_url} alt="logo" />
              ) : (
                <span className="rcfg__logo-text">{cfg.logo_text || '—'}</span>
              )}
            </div>
            <div className="rcfg__logo-actions">
              <input
                ref={fileRef}
                type="file"
                accept="image/png,image/jpeg"
                disabled={!canEdit || uploading}
                onChange={onPickLogo}
                className="rcfg__file"
              />
              <p className="rcfg__hint">Ảnh PNG/JPG, tối đa ~500KB. Lưu ngay khi chọn.</p>
              {uploading && <p className="rcfg__hint">Đang tải logo…</p>}
            </div>
          </div>
          <label className="field">
            <span>Tên tiệm</span>
            <input className="input" type="text" value={cfg.shop_name || ''} disabled={!canEdit}
              onChange={(e) => set('shop_name', e.target.value)} />
          </label>
          <label className="field">
            <span>Logo chữ (dự phòng khi chưa có ảnh)</span>
            <input className="input" type="text" maxLength={16} value={cfg.logo_text || ''} disabled={!canEdit}
              onChange={(e) => set('logo_text', e.target.value)} />
          </label>
        </div>

        {/* ── Chân phiếu (footer song ngữ) ───────────────────────── */}
        <div className="card">
          <h3 className="card__title">Chân phiếu (Footer)</h3>
          {FOOTER_FIELDS.map((f) => (
            <label className="field" key={f.key}>
              <span>{f.label}</span>
              <input className="input" type="text" value={cfg[f.key] || ''} disabled={!canEdit}
                onChange={(e) => set(f.key, e.target.value)} />
            </label>
          ))}
        </div>

        {/* ── Ghi chú trách nhiệm (song ngữ) ─────────────────────── */}
        <div className="card">
          <div className="rcfg__card-head">
            <h3 className="card__title">Ghi chú trách nhiệm</h3>
            <label className="rcfg__switch">
              <input type="checkbox" checked={!!cfg.note_enabled} disabled={!canEdit}
                onChange={(e) => set('note_enabled', e.target.checked)} />
              <span>{cfg.note_enabled ? 'Hiện' : 'Ẩn'}</span>
            </label>
          </div>
          <label className="field">
            <span>Tiếng Việt</span>
            <textarea className="input rcfg__ta" rows={3} value={cfg.note_vi || ''} disabled={!canEdit || !cfg.note_enabled}
              onChange={(e) => set('note_vi', e.target.value)} />
          </label>
          <label className="field">
            <span>English</span>
            <textarea className="input rcfg__ta" rows={3} value={cfg.note_en || ''} disabled={!canEdit || !cfg.note_enabled}
              onChange={(e) => set('note_en', e.target.value)} />
          </label>
        </div>

        {/* ── Phụ thu (Tết) — mặc định tắt ───────────────────────── */}
        <div className="card">
          <div className="rcfg__card-head">
            <h3 className="card__title">Phụ thu (chỉ dùng Tết)</h3>
            <label className="rcfg__switch">
              <input type="checkbox" checked={!!cfg.surcharge_enabled} disabled={!canEdit}
                onChange={(e) => set('surcharge_enabled', e.target.checked)} />
              <span>{cfg.surcharge_enabled ? 'Bật' : 'Tắt'}</span>
            </label>
          </div>
          <label className="field">
            <span>Phụ thu (% trên tổng món)</span>
            <input className="input" type="number" min={0} max={100} step={1}
              value={cfg.surcharge_percent ?? 0} disabled={!canEdit || !cfg.surcharge_enabled}
              onChange={(e) => set('surcharge_percent', Number(e.target.value) || 0)} />
          </label>
          <label className="field">
            <span>Nhãn (Tiếng Việt)</span>
            <input className="input" type="text" value={cfg.surcharge_label_vi || ''} disabled={!canEdit || !cfg.surcharge_enabled}
              onChange={(e) => set('surcharge_label_vi', e.target.value)} />
          </label>
          <label className="field">
            <span>Nhãn (English)</span>
            <input className="input" type="text" value={cfg.surcharge_label_en || ''} disabled={!canEdit || !cfg.surcharge_enabled}
              onChange={(e) => set('surcharge_label_en', e.target.value)} />
          </label>
        </div>

        {error && <div className="alert alert--error">{error}</div>}
        {canEdit && (
          <button className="btn btn--primary btn--xl btn--block" onClick={save} disabled={saving}>
            {saving ? 'Đang lưu…' : saved ? '✓ Đã lưu' : 'Lưu mẫu phiếu'}
          </button>
        )}
      </div>

      <div className="rcfg__preview">
        <div className="rcfg__preview-label">Xem trước (khổ 80mm)</div>
        <div className="rcp-preview">
          <BillContent config={preview} order={SAMPLE_ORDER} />
        </div>
      </div>
    </div>
  )
}
