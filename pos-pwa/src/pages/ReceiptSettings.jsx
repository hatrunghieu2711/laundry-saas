import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import BillContent from '../components/Bill'
import { ApiError, api } from '../lib/api'
import {
  BLOCK_META,
  DEFAULT_NOTE_EN,
  DEFAULT_NOTE_VI,
  clearReceiptCache,
  isNarrow,
  isText,
  normalizeReceipt,
} from '../lib/receipt'

// Đơn mẫu để preview realtime (có phụ thu + giảm + đã thanh toán để thấy đủ khối).
const SAMPLE_ORDER = {
  order_code: 'B1-00042',
  subtotal: 185000,
  surcharge_amount: 18500,
  discount_amount: 15000,
  surcharge_reason: 'Phụ thu Tết',
  discount_reason: 'Khách quen',
  total_amount: 188500,
  payment_status: 'paid',
  pickup_at: '2026-06-14T03:30:00Z',
  created_at: '2026-06-13T09:15:00Z',
  customer_name: 'Chị Lan',
  customer_phone: '0905 123 456',
  items: [
    { id: 1, service_name: 'Giặt sấy (≤3kg)', quantity: 1, unit_price: 60000, subtotal: 60000 },
    { id: 2, service_name: 'Áo Vest', quantity: 2, unit_price: 60000, subtotal: 120000 },
    { id: 3, service_name: 'Giặt thường', quantity: 1, unit_price: 5000, subtotal: 5000 },
  ],
}

// ── chuyển đổi blocks[] ↔ rows (mảng hàng, mỗi hàng 1-2 khối) ──
function blocksToRows(blocks) {
  const map = new Map()
  blocks.forEach((b) => {
    const r = b.row ?? 0
    if (!map.has(r)) map.set(r, [])
    map.get(r).push(b)
  })
  return [...map.keys()]
    .sort((a, b) => a - b)
    .map((k) => map.get(k).slice().sort((a, b) => (a.col === 'right' ? 1 : 0) - (b.col === 'right' ? 1 : 0)))
}
function rowsToBlocks(rows) {
  const out = []
  rows.forEach((row, ri) => {
    if (row.length === 1) out.push({ ...row[0], row: ri, col: 'full' })
    else row.forEach((b, ci) => out.push({ ...b, row: ri, col: ci === 0 ? 'left' : 'right' }))
  })
  return out
}

export default function ReceiptSettings() {
  const { user } = useAuth()
  const canEdit = user?.role === 'owner'

  const [bilingual, setBilingual] = useState(true)
  const [logoUrl, setLogoUrl] = useState('')
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  const [editBlk, setEditBlk] = useState(null) // {rowIdx, cellIdx, block}
  const [editContent, setEditContent] = useState({})
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)
  const dragIdx = useRef(null)

  useEffect(() => {
    api
      .get('/settings/receipt')
      .then((c) => {
        const n = normalizeReceipt(c)
        setBilingual(n.bilingual)
        setLogoUrl(n.logo_url)
        setRows(blocksToRows(n.blocks))
      })
      .catch((e) => setError(e?.message || 'Không tải được cấu hình phiếu'))
  }, [])

  const dirty = () => setSaved(false)
  const mutate = (fn) => { dirty(); setRows((rs) => fn(rs.map((r) => r.slice()))) }

  const toggle = (ri, ci) => mutate((rs) => {
    rs[ri][ci] = { ...rs[ri][ci], enabled: !rs[ri][ci].enabled }
    return rs
  })
  const moveRow = (ri, dir) => mutate((rs) => {
    const j = ri + dir
    if (j < 0 || j >= rs.length) return rs
    ;[rs[ri], rs[j]] = [rs[j], rs[ri]]
    return rs
  })
  const canPairDown = (ri) =>
    rows[ri].length === 1 && rows[ri + 1]?.length === 1 &&
    isNarrow(rows[ri][0].type) && isNarrow(rows[ri + 1][0].type)
  const pairDown = (ri) => mutate((rs) => {
    rs[ri] = [rs[ri][0], rs[ri + 1][0]]
    rs.splice(ri + 1, 1)
    return rs
  })
  const splitRow = (ri) => mutate((rs) => {
    const [a, b] = rs[ri]
    rs.splice(ri, 1, [a], [b])
    return rs
  })
  const addCustom = () => mutate((rs) => {
    const id = `custom_${Date.now()}`
    rs.push([{ id, type: 'custom_text', enabled: true, row: rs.length, col: 'full',
      content: { vi: 'Nội dung tự do…', en: 'Custom text…' } }])
    return rs
  })
  const removeBlock = (ri) => mutate((rs) => { rs.splice(ri, 1); return rs })

  // Kéo-thả sắp xếp hàng.
  const onDrop = (ti) => mutate((rs) => {
    const di = dragIdx.current
    dragIdx.current = null
    if (di == null || di === ti) return rs
    const [moved] = rs.splice(di, 1)
    rs.splice(ti, 0, moved)
    return rs
  })

  // Sửa nội dung khối text.
  const openEdit = (ri, ci) => {
    const block = rows[ri][ci]
    setEditBlk({ ri, ci, type: block.type })
    setEditContent({ ...(block.content || {}) })
    setError('')
  }
  const saveEdit = () => mutateThenClose()
  const mutateThenClose = () => {
    const { ri, ci } = editBlk
    dirty()
    setRows((rs) => {
      const copy = rs.map((r) => r.slice())
      copy[ri][ci] = { ...copy[ri][ci], content: { ...editContent } }
      return copy
    })
    setEditBlk(null)
  }

  const onPickLogo = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    if (!['image/png', 'image/jpeg', 'image/jpg'].includes(file.type)) {
      setError('Chỉ nhận ảnh PNG hoặc JPG.'); if (fileRef.current) fileRef.current.value = ''; return
    }
    if (file.size > 512 * 1024) {
      setError('Ảnh quá lớn (tối đa ~500KB).'); if (fileRef.current) fileRef.current.value = ''; return
    }
    setUploading(true)
    try {
      const fd = new FormData()
      fd.append('file', file)
      const updated = await api.upload('/settings/receipt/logo', fd)
      clearReceiptCache()
      setLogoUrl(updated.logo_url || '')
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403
        ? 'Chỉ chủ chuỗi (owner) mới đổi được logo.'
        : err?.message || 'Tải logo thất bại')
    } finally {
      setUploading(false)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      await api.put('/settings/receipt', { bilingual, blocks: rowsToBlocks(rows) })
      clearReceiptCache()
      setSaved(true)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403
        ? 'Chỉ chủ chuỗi (owner) mới lưu được mẫu phiếu.'
        : e?.message || 'Không lưu được cấu hình')
    } finally {
      setSaving(false)
    }
  }

  const previewConfig = useMemo(
    () => (rows ? { bilingual, logo_url: logoUrl, blocks: rowsToBlocks(rows) } : null),
    [rows, bilingual, logoUrl],
  )

  if (!rows) return <p className="shift__hint">{error || 'Đang tải cấu hình phiếu…'}</p>

  return (
    <div className="rcfg">
      <div className="rcfg__editor">
        <h2 className="services__title">Mẫu phiếu in — bố cục theo khối</h2>
        {!canEdit && <div className="alert alert--error">Chỉ chủ chuỗi (owner) mới sửa được. Bạn đang xem.</div>}

        <div className="card">
          <div className="rcfg__card-head">
            <h3 className="card__title">Tùy chọn chung</h3>
            <label className="rcfg__switch">
              <input type="checkbox" checked={bilingual} disabled={!canEdit}
                onChange={(e) => { dirty(); setBilingual(e.target.checked) }} />
              <span>Hiện tiếng Anh</span>
            </label>
          </div>
          <p className="rcfg__hint">
            Kéo-thả hoặc dùng nút ↑/↓ để sắp xếp. Khối hẹp (giờ nhận/giao, số đơn, trạng thái TT)
            có thể <strong>Ghép</strong> 2 khối vào 1 hàng. Bấm ✎ để sửa nội dung khối văn bản.
          </p>
        </div>

        <div className="card">
          <h3 className="card__title">Các khối trên phiếu</h3>
          <div className="bld-list">
            {rows.map((row, ri) => (
              <div
                key={row.map((b) => b.id).join('+')}
                className="bld-row"
                draggable={canEdit}
                onDragStart={() => { dragIdx.current = ri }}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => onDrop(ri)}
              >
                <span className="bld-row__grip" title="Kéo để sắp xếp">⠿</span>
                <div className="bld-row__cells">
                  {row.map((blk, ci) => {
                    const meta = BLOCK_META[blk.type] || { label: blk.type }
                    return (
                      <div className={`bld-cell ${blk.enabled ? '' : 'bld-cell--off'}`} key={blk.id}>
                        <label className="bld-cell__toggle">
                          <input type="checkbox" checked={blk.enabled} disabled={!canEdit}
                            onChange={() => toggle(ri, ci)} />
                        </label>
                        <span className="bld-cell__label">
                          {meta.label}
                          {row.length === 2 && <span className="bld-cell__half">½</span>}
                        </span>
                        <span className="bld-cell__acts">
                          {isText(blk.type) && (
                            <button className="icon-btn" disabled={!canEdit} title="Sửa nội dung" onClick={() => openEdit(ri, ci)}>✎</button>
                          )}
                          {blk.type === 'custom_text' && (
                            <button className="icon-btn" disabled={!canEdit} title="Xóa khối" onClick={() => removeBlock(ri)}>🗑</button>
                          )}
                        </span>
                      </div>
                    )
                  })}
                </div>
                <div className="bld-row__ops">
                  <button className="icon-btn" disabled={!canEdit || ri === 0} title="Lên" onClick={() => moveRow(ri, -1)}>↑</button>
                  <button className="icon-btn" disabled={!canEdit || ri === rows.length - 1} title="Xuống" onClick={() => moveRow(ri, +1)}>↓</button>
                  {row.length === 1 && canPairDown(ri) && (
                    <button className="icon-btn icon-btn--wide" disabled={!canEdit} title="Ghép với hàng dưới" onClick={() => pairDown(ri)}>⊞ Ghép</button>
                  )}
                  {row.length === 2 && (
                    <button className="icon-btn icon-btn--wide" disabled={!canEdit} title="Tách thành 2 hàng" onClick={() => splitRow(ri)}>⊟ Tách</button>
                  )}
                </div>
              </div>
            ))}
          </div>
          {canEdit && (
            <button className="btn btn--ghost btn--lg btn--block" onClick={addCustom} style={{ marginTop: 10 }}>
              ＋ Thêm khối văn bản tự do
            </button>
          )}
        </div>

        {error && !editBlk && <div className="alert alert--error">{error}</div>}
        {canEdit && (
          <button className="btn btn--primary btn--xl btn--block" onClick={save} disabled={saving}>
            {saving ? 'Đang lưu…' : saved ? '✓ Đã lưu' : 'Lưu mẫu phiếu'}
          </button>
        )}
      </div>

      <div className="rcfg__preview">
        <div className="rcfg__preview-label">Xem trước (khổ 80mm)</div>
        <div className="rcp-preview">
          <BillContent config={previewConfig} order={SAMPLE_ORDER} />
        </div>
      </div>

      {/* Popup sửa nội dung khối text */}
      {editBlk && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal">
            <h3 className="modal__title">Sửa: {BLOCK_META[editBlk.type]?.label}</h3>

            {editBlk.type === 'logo' && (
              <>
                <div className="rcfg__logo">
                  <div className="rcfg__logo-prev">
                    {logoUrl ? <img src={logoUrl} alt="logo" /> : <span className="rcfg__logo-text">{editContent.logo_text || '—'}</span>}
                  </div>
                  <div className="rcfg__logo-actions">
                    <input ref={fileRef} type="file" accept="image/png,image/jpeg" className="rcfg__file"
                      disabled={!canEdit || uploading} onChange={onPickLogo} />
                    <p className="rcfg__hint">Ảnh PNG/JPG ≤500KB. Lưu ngay khi chọn.</p>
                    {uploading && <p className="rcfg__hint">Đang tải logo…</p>}
                  </div>
                </div>
                <label className="field"><span>Tên tiệm</span>
                  <input className="input" value={editContent.shop_name || ''} onChange={(e) => setEditContent((c) => ({ ...c, shop_name: e.target.value }))} /></label>
                <label className="field"><span>Logo chữ (khi chưa có ảnh)</span>
                  <input className="input" maxLength={16} value={editContent.logo_text || ''} onChange={(e) => setEditContent((c) => ({ ...c, logo_text: e.target.value }))} /></label>
              </>
            )}

            {(editBlk.type === 'note' || editBlk.type === 'custom_text') && (
              <>
                <label className="field"><span>Tiếng Việt</span>
                  <textarea className="input rcfg__ta" rows={3} value={editContent.vi || ''} onChange={(e) => setEditContent((c) => ({ ...c, vi: e.target.value }))} /></label>
                {bilingual && (
                  <label className="field"><span>English</span>
                    <textarea className="input rcfg__ta" rows={3} value={editContent.en || ''} onChange={(e) => setEditContent((c) => ({ ...c, en: e.target.value }))} /></label>
                )}
                {editBlk.type === 'note' && (
                  <button className="btn btn--ghost btn--sm" onClick={() => setEditContent({ vi: DEFAULT_NOTE_VI, en: DEFAULT_NOTE_EN })}>Khôi phục ghi chú mẫu</button>
                )}
              </>
            )}

            {editBlk.type === 'footer_contact' && (
              <>
                {[['hotline', 'Hotline'], ['web', 'Web'], ['address', 'Địa chỉ / Add'],
                  ['zalo_wa_kakao', 'Zalo / WA / Kakao'], ['open_hours', 'Giờ mở cửa / OPEN'],
                  ['tagline', 'Dòng cảm ơn']].map(([k, label]) => (
                  <label className="field" key={k}><span>{label}</span>
                    <input className="input" value={editContent[k] || ''} onChange={(e) => setEditContent((c) => ({ ...c, [k]: e.target.value }))} /></label>
                ))}
              </>
            )}

            <div className="modal__actions modal__actions--row">
              <button className="btn btn--ghost btn--lg" onClick={() => setEditBlk(null)}>Quay lại</button>
              <button className="btn btn--primary btn--lg" onClick={saveEdit} disabled={!canEdit}>Xong</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
