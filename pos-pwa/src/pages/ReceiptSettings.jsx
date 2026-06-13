import { useEffect, useMemo, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import BillContent from '../components/Bill'
import { ApiError, api } from '../lib/api'
import { BLOCK_LABEL, clearReceiptCache, normalizeReceipt } from '../lib/receipt'

// Dữ liệu mẫu để preview (đúng khổ 80mm, không gọi backend).
const SAMPLE_ORDER = {
  order_code: 'B1-00042',
  total_amount: 185000,
  pickup_at: '2026-06-14T03:30:00Z', // 10:30 14/06 (giờ VN)
  created_at: '2026-06-13T09:15:00Z',
  created_by_name: 'NV A',
  customer_name: 'Chị Lan',
  items: [
    { id: 1, service_name: 'Giặt sấy (≤3kg)', quantity: 1, subtotal: 60000 },
    { id: 2, service_name: 'Áo Vest', quantity: 2, subtotal: 120000 },
    { id: 3, service_name: 'Giặt thường', quantity: 1, subtotal: 5000 },
  ],
}

const TEXT_FIELDS = [
  { key: 'shop_name', label: 'Tên tiệm' },
  { key: 'logo_text', label: 'Logo (chữ, vd “2H”)' },
  { key: 'address', label: 'Địa chỉ' },
  { key: 'phone', label: 'Số điện thoại' },
  { key: 'open_hours', label: 'Giờ mở cửa' },
  { key: 'footer_text', label: 'Lời cảm ơn (chân phiếu)' },
]

export default function ReceiptSettings() {
  const { user } = useAuth()
  const canEdit = user?.role === 'owner'

  const [cfg, setCfg] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    api
      .get('/settings/receipt')
      .then((c) => setCfg(normalizeReceipt(c)))
      .catch((e) => setError(e?.message || 'Không tải được cấu hình phiếu'))
  }, [])

  const setText = (k, v) => {
    setSaved(false)
    setCfg((c) => ({ ...c, [k]: v }))
  }
  const toggleBlock = (key) => {
    setSaved(false)
    setCfg((c) => ({
      ...c,
      blocks: c.blocks.map((b) => (b.key === key ? { ...b, enabled: !b.enabled } : b)),
    }))
  }
  const move = (i, dir) => {
    setSaved(false)
    setCfg((c) => {
      const blocks = [...c.blocks]
      const j = i + dir
      if (j < 0 || j >= blocks.length) return c
      ;[blocks[i], blocks[j]] = [blocks[j], blocks[i]]
      return { ...c, blocks }
    })
  }

  // Chuẩn hoá order = vị trí mảng để preview/lưu khớp thứ tự đang hiển thị.
  const ordered = useMemo(
    () => (cfg ? { ...cfg, blocks: cfg.blocks.map((b, i) => ({ ...b, order: i })) } : null),
    [cfg],
  )

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await api.put('/settings/receipt', ordered)
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

  if (!cfg) {
    return <p className="shift__hint">{error || 'Đang tải cấu hình phiếu…'}</p>
  }

  return (
    <div className="rcfg">
      <div className="rcfg__editor">
        <h2 className="services__title">Mẫu phiếu in</h2>
        {!canEdit && (
          <div className="alert alert--error">Chỉ chủ chuỗi (owner) mới sửa được. Bạn đang xem.</div>
        )}

        <div className="card">
          <h3 className="card__title">Thông tin tiệm</h3>
          {TEXT_FIELDS.map((f) => (
            <label className="field" key={f.key}>
              <span>{f.label}</span>
              <input
                className="input"
                type="text"
                value={cfg[f.key] || ''}
                disabled={!canEdit}
                onChange={(e) => setText(f.key, e.target.value)}
              />
            </label>
          ))}
        </div>

        <div className="card">
          <h3 className="card__title">Khối trên phiếu (bật/tắt · sắp thứ tự)</h3>
          <div className="blk-list">
            {cfg.blocks.map((b, i) => (
              <div className={`blk ${b.enabled ? '' : 'blk--off'}`} key={b.key}>
                <div className="blk__order">
                  <button className="blk__arrow" disabled={!canEdit || i === 0} onClick={() => move(i, -1)} aria-label="Lên">↑</button>
                  <button className="blk__arrow" disabled={!canEdit || i === cfg.blocks.length - 1} onClick={() => move(i, +1)} aria-label="Xuống">↓</button>
                </div>
                <span className="blk__label">{BLOCK_LABEL[b.key] || b.key}</span>
                <label className="blk__chk">
                  <input type="checkbox" checked={b.enabled} disabled={!canEdit} onChange={() => toggleBlock(b.key)} />
                  <span>{b.enabled ? 'Hiện' : 'Ẩn'}</span>
                </label>
              </div>
            ))}
          </div>
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
          <BillContent config={ordered} order={SAMPLE_ORDER} paid={185000} method="cash" />
        </div>
      </div>
    </div>
  )
}
