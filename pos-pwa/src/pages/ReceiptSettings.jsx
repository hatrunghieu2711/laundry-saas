import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import BillContent from '../components/Bill'
import { ApiError, api } from '../lib/api'
import {
  ADDABLE,
  BLOCK_LABELS,
  BLOCK_META,
  BLOCK_VALUES,
  blockListLabel,
  canItalic,
  clearReceiptCache,
  defaultAlign,
  isField,
  normalizeReceipt,
} from '../lib/receipt'

const SAMPLE_ORDER = {
  order_code: 'B1-00042',
  subtotal: 185000, surcharge_amount: 18500, discount_amount: 15000,
  surcharge_reason: 'Phụ thu Tết', discount_reason: 'Khách quen',
  total_amount: 188500, payment_status: 'paid',
  pickup_at: '2026-06-14T03:30:00Z', created_at: '2026-06-13T09:15:00Z',
  customer_name: 'Chị Lan', customer_phone: '0905 123 456',
  items: [
    { id: 1, service_name: 'Giặt sấy (≤3kg)', quantity: 1, unit_price: 60000, subtotal: 60000 },
    { id: 2, service_name: 'Áo Vest', quantity: 2, unit_price: 60000, subtotal: 120000 },
    { id: 3, service_name: 'Giặt thường', quantity: 1, unit_price: 5000, subtotal: 5000 },
  ],
}

const blocksToRows = (blocks) => {
  const map = new Map()
  blocks.forEach((b) => {
    const r = b.row ?? 0
    if (!map.has(r)) map.set(r, [])
    map.get(r).push(b)
  })
  return [...map.keys()].sort((a, b) => a - b)
    .map((k) => map.get(k).slice().sort((a, b) => (a.col === 'right' ? 1 : 0) - (b.col === 'right' ? 1 : 0)))
}
const rowsToBlocks = (rows) => {
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
  const [trackBaseUrl, setTrackBaseUrl] = useState('')
  const [rows, setRows] = useState(null)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [dragRi, setDragRi] = useState(null)

  const [editBlk, setEditBlk] = useState(null) // {ri, ci, type}
  const [editContent, setEditContent] = useState({})
  const [editFmt, setEditFmt] = useState({ bold: false, align: 'left', size: 'normal' })
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  useEffect(() => {
    api.get('/settings/receipt')
      .then((c) => {
        const n = normalizeReceipt(c)
        setBilingual(n.bilingual)
        setLogoUrl(n.logo_url)
        setTrackBaseUrl(n.track_base_url)
        setRows(blocksToRows(n.blocks))
      })
      .catch((e) => setError(e?.message || 'Không tải được cấu hình phiếu'))
  }, [])

  const dirty = () => setSaved(false)
  const mutate = (fn) => { dirty(); setRows((rs) => fn(rs.map((r) => r.slice()))) }

  const toggle = (ri, ci) => mutate((rs) => { rs[ri][ci] = { ...rs[ri][ci], enabled: !rs[ri][ci].enabled }; return rs })
  const moveRow = (ri, dir) => mutate((rs) => {
    const j = ri + dir
    if (j < 0 || j >= rs.length) return rs
    ;[rs[ri], rs[j]] = [rs[j], rs[ri]]
    return rs
  })
  const canPairDown = (ri) => rows[ri].length === 1 && rows[ri + 1]?.length === 1
  const pairDown = (ri) => mutate((rs) => { rs[ri] = [rs[ri][0], rs[ri + 1][0]]; rs.splice(ri + 1, 1); return rs })
  const splitRow = (ri) => mutate((rs) => { const [a, b] = rs[ri]; rs.splice(ri, 1, [a], [b]); return rs })
  const removeBlock = (ri) => mutate((rs) => { rs.splice(ri, 1); return rs })

  // Nhân bản khối: chèn khối mới ngay dưới (giữ type + nội dung + định dạng),
  // đặt full hàng + enabled (Stage 5.9).
  const copyBlock = (ri, ci) => mutate((rs) => {
    const src = rs[ri][ci]
    const clone = {
      ...src, id: `${src.type}_${Date.now()}`, col: 'full', enabled: true,
      content: { ...(src.content || {}) },
    }
    rs.splice(ri + 1, 0, [clone])
    return rs
  })

  const addBlock = (type) => mutate((rs) => {
    const id = `${type}_${Date.now()}`
    const content = type === 'custom_text' ? { vi: 'Nội dung tự do…', en: 'Custom text…' }
      : type === 'divider' ? { style: 'dashed' }
        : type === 'spacer' ? { height: 'small' } : {}
    rs.push([{ id, type, enabled: true, row: rs.length, col: 'full', bold: false, italic: false, title: false, align: null, size: 'normal', content }])
    return rs
  })

  // Kéo-thả: thả lên thân hàng = sắp xếp; thả lên ô "ghép" của hàng đơn khác = ghép.
  const reorderTo = (ti) => mutate((rs) => {
    const di = dragRi
    if (di == null || di === ti) return rs
    const [m] = rs.splice(di, 1)
    rs.splice(di < ti ? ti - 1 : ti, 0, m)
    return rs
  })
  const pairWith = (ti) => mutate((rs) => {
    const di = dragRi
    if (di == null || di === ti || rs[di].length !== 1 || rs[ti].length !== 1) return rs
    const dragged = rs[di][0]
    const next = rs.map((r, i) => (i === ti ? [r[0], dragged] : r)).filter((_, i) => i !== di)
    return next
  })

  const openEdit = (ri, ci) => {
    const b = rows[ri][ci]
    setEditBlk({ ri, ci, type: b.type })
    setEditContent({ ...(b.content || {}) })
    // Khối field: bold tách nhãn/giá trị (None → fallback bold cũ). Khác: 1 cờ bold.
    setEditFmt({
      bold: !!b.bold,
      bold_label: b.bold_label ?? !!b.bold,
      bold_value: b.bold_value ?? !!b.bold,
      italic: !!b.italic,
      title: !!b.title,
      align: b.align || defaultAlign(b.type),
      size: b.size || 'normal',
    })
    setError('')
  }
  const saveEdit = () => {
    const { ri, ci } = editBlk
    dirty()
    setRows((rs) => {
      const copy = rs.map((r) => r.slice())
      copy[ri][ci] = { ...copy[ri][ci], content: { ...editContent }, ...editFmt }
      return copy
    })
    setEditBlk(null)
  }
  const setC = (k, v) => setEditContent((c) => ({ ...c, [k]: v }))
  const setF = (k, v) => setEditFmt((f) => ({ ...f, [k]: v }))

  const onPickLogo = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    setError('')
    if (!['image/png', 'image/jpeg', 'image/jpg'].includes(file.type)) { setError('Chỉ nhận ảnh PNG hoặc JPG.'); if (fileRef.current) fileRef.current.value = ''; return }
    if (file.size > 512 * 1024) { setError('Ảnh quá lớn (tối đa ~500KB).'); if (fileRef.current) fileRef.current.value = ''; return }
    setUploading(true)
    try {
      const fd = new FormData(); fd.append('file', file)
      const updated = await api.upload('/settings/receipt/logo', fd)
      clearReceiptCache(); setLogoUrl(updated.logo_url || '')
    } catch (err) {
      setError(err instanceof ApiError && err.status === 403 ? 'Chỉ owner mới đổi được logo.' : err?.message || 'Tải logo thất bại')
    } finally { setUploading(false); if (fileRef.current) fileRef.current.value = '' }
  }

  const save = async () => {
    setSaving(true); setError('')
    try {
      await api.put('/settings/receipt', { bilingual, track_base_url: trackBaseUrl.trim(), blocks: rowsToBlocks(rows) })
      clearReceiptCache(); setSaved(true)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? 'Chỉ owner mới lưu được mẫu phiếu.' : e?.message || 'Không lưu được cấu hình')
    } finally { setSaving(false) }
  }

  const previewConfig = useMemo(
    () => (rows ? { bilingual, logo_url: logoUrl, track_base_url: trackBaseUrl, blocks: rowsToBlocks(rows) } : null),
    [rows, bilingual, logoUrl, trackBaseUrl],
  )

  if (!rows) return <p className="shift__hint">{error || 'Đang tải cấu hình phiếu…'}</p>

  const draggedSingle = dragRi != null && rows[dragRi]?.length === 1

  return (
    <div className="rcfg">
      <div className="rcfg__editor">
        <h2 className="services__title">Mẫu phiếu in — bố cục theo khối</h2>
        {!canEdit && <div className="alert alert--error">Chỉ chủ chuỗi (owner) mới sửa được. Bạn đang xem.</div>}

        <div className="card">
          <div className="rcfg__card-head">
            <h3 className="card__title">Tùy chọn chung</h3>
            <label className="rcfg__switch">
              <input type="checkbox" checked={bilingual} disabled={!canEdit} onChange={(e) => { dirty(); setBilingual(e.target.checked) }} />
              <span>Hiện tiếng Anh</span>
            </label>
          </div>
          <p className="rcfg__hint">
            Kéo-thả (hoặc ↑/↓) để sắp xếp. Kéo 1 khối thả vào ô <strong>＋ghép</strong> của khối khác,
            hoặc nút <strong>Ghép/Tách</strong>, để xếp 2 khối/hàng (tự do, không giới hạn).
            Bấm ✎ để sửa nhãn, nội dung &amp; định dạng (đậm · nghiêng · căn lề · cỡ chữ).
          </p>
          <label className="field">
            <span>Link tra cứu cho QR (base URL + mã đơn)</span>
            <input className="input" type="text" value={trackBaseUrl} disabled={!canEdit}
              placeholder="https://track.giatui2h.com/track/"
              onChange={(e) => { dirty(); setTrackBaseUrl(e.target.value) }} />
          </label>
          <p className="rcfg__hint">Để trống = dùng mặc định track.giatui2h.com. QR = link này + mã đơn.</p>
        </div>

        <div className="card">
          <h3 className="card__title">Các khối trên phiếu</h3>
          <div className="bld-list">
            {rows.map((row, ri) => (
              <div
                key={row.map((b) => b.id).join('+')}
                className={`bld-row ${dragRi === ri ? 'bld-row--drag' : ''}`}
                draggable={canEdit}
                onDragStart={() => setDragRi(ri)}
                onDragEnd={() => setDragRi(null)}
                onDragOver={(e) => e.preventDefault()}
                onDrop={() => { reorderTo(ri); setDragRi(null) }}
              >
                <span className="bld-row__grip" title="Kéo để sắp xếp / ghép">⠿</span>
                <div className="bld-row__cells">
                  {row.map((blk, ci) => (
                    <div className={`bld-cell ${blk.enabled ? '' : 'bld-cell--off'}`} key={blk.id}>
                      <label className="bld-cell__toggle">
                        <input type="checkbox" checked={blk.enabled} disabled={!canEdit} onChange={() => toggle(ri, ci)} />
                      </label>
                      <span className="bld-cell__label" title={blockListLabel(blk)}>
                        {blockListLabel(blk)}
                        {row.length === 2 && <span className="bld-cell__half">½</span>}
                      </span>
                      <span className="bld-cell__acts">
                        <button className="icon-btn" disabled={!canEdit} title="Sửa nhãn / nội dung / định dạng" onClick={() => openEdit(ri, ci)}>✎</button>
                        <button className="icon-btn" disabled={!canEdit} title="Nhân bản khối" onClick={() => copyBlock(ri, ci)}>⧉</button>
                        {['custom_text', 'divider', 'spacer'].includes(blk.type) && (
                          <button className="icon-btn" disabled={!canEdit} title="Xóa khối" onClick={() => removeBlock(ri)}>🗑</button>
                        )}
                      </span>
                    </div>
                  ))}
                  {/* Ô đích ghép: hiện khi đang kéo 1 khối đơn khác. */}
                  {canEdit && draggedSingle && dragRi !== ri && row.length === 1 && (
                    <div className="bld-pairzone" onDragOver={(e) => e.preventDefault()}
                      onDrop={(e) => { e.stopPropagation(); pairWith(ri); setDragRi(null) }}>
                      ＋ ghép cạnh
                    </div>
                  )}
                </div>
                <div className="bld-row__ops">
                  <button className="icon-btn" disabled={!canEdit || ri === 0} title="Lên" onClick={() => moveRow(ri, -1)}>↑</button>
                  <button className="icon-btn" disabled={!canEdit || ri === rows.length - 1} title="Xuống" onClick={() => moveRow(ri, +1)}>↓</button>
                  {row.length === 1 && canPairDown(ri) && (
                    <button className="icon-btn icon-btn--wide" disabled={!canEdit} title="Ghép với hàng dưới" onClick={() => pairDown(ri)}>⊞</button>
                  )}
                  {row.length === 2 && (
                    <button className="icon-btn icon-btn--wide" disabled={!canEdit} title="Tách thành 2 hàng" onClick={() => splitRow(ri)}>⊟</button>
                  )}
                </div>
              </div>
            ))}
          </div>
          {canEdit && (
            <div className="bld-add">
              {ADDABLE.map((a) => (
                <button key={a.type} className="btn btn--ghost btn--sm" onClick={() => addBlock(a.type)}>{a.label}</button>
              ))}
            </div>
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

      {editBlk && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal modal--scroll">
            <h3 className="modal__title">Sửa: {BLOCK_META[editBlk.type]?.label}</h3>

            {/* Logo: upload ảnh */}
            {editBlk.type === 'logo' && (
              <div className="rcfg__logo">
                <div className="rcfg__logo-prev">
                  {logoUrl ? <img src={logoUrl} alt="logo" /> : <span className="rcfg__logo-text">{editContent.logo_text || '—'}</span>}
                </div>
                <div className="rcfg__logo-actions">
                  <input ref={fileRef} type="file" accept="image/png,image/jpeg" className="rcfg__file" disabled={!canEdit || uploading} onChange={onPickLogo} />
                  <p className="rcfg__hint">Ảnh PNG/JPG ≤500KB. Lưu ngay khi chọn.</p>
                  {uploading && <p className="rcfg__hint">Đang tải logo…</p>}
                </div>
              </div>
            )}

            {/* Divider: kiểu kẻ */}
            {editBlk.type === 'divider' && (
              <div className="fmt-row"><span>Kiểu kẻ</span>
                <div className="seg seg--sm">
                  <button className={`seg__btn ${(editContent.style || 'dashed') === 'dashed' ? 'seg__btn--active' : ''}`} onClick={() => setC('style', 'dashed')}>- - -</button>
                  <button className={`seg__btn ${editContent.style === 'solid' ? 'seg__btn--active' : ''}`} onClick={() => setC('style', 'solid')}>───</button>
                </div>
              </div>
            )}
            {/* Spacer: chiều cao */}
            {editBlk.type === 'spacer' && (
              <div className="fmt-row"><span>Chiều cao</span>
                <div className="seg seg--sm">
                  <button className={`seg__btn ${(editContent.height || 'small') === 'small' ? 'seg__btn--active' : ''}`} onClick={() => setC('height', 'small')}>Nhỏ</button>
                  <button className={`seg__btn ${editContent.height === 'medium' ? 'seg__btn--active' : ''}`} onClick={() => setC('height', 'medium')}>Vừa</button>
                </div>
              </div>
            )}

            {/* Giá trị text owner nhập (logo / văn bản tự do) */}
            {(BLOCK_VALUES[editBlk.type] || []).filter((f) => !f.en || bilingual).map((f) => (
              <label className="field" key={f.key}>
                <span>{f.label}</span>
                {f.area
                  ? <textarea className="input rcfg__ta" rows={3} value={editContent[f.key] || ''} onChange={(e) => setC(f.key, e.target.value)} />
                  : <input className="input" value={editContent[f.key] || ''} onChange={(e) => setC(f.key, e.target.value)} />}
              </label>
            ))}

            {/* Nhãn hiển thị (song ngữ) */}
            {(BLOCK_LABELS[editBlk.type] || []).length > 0 && (
              <div className="lbl-edit">
                <div className="lbl-edit__title">Nhãn hiển thị {bilingual ? '(Việt / Anh)' : '(Tiếng Việt)'}</div>
                {BLOCK_LABELS[editBlk.type].map((l) => (
                  <div className="lbl-edit__row" key={l.key}>
                    <input className="input" placeholder={l.vi} value={editContent[`${l.key}_vi`] ?? ''} onChange={(e) => setC(`${l.key}_vi`, e.target.value)} />
                    {bilingual && (
                      <input className="input" placeholder={l.en} value={editContent[`${l.key}_en`] ?? ''} onChange={(e) => setC(`${l.key}_en`, e.target.value)} />
                    )}
                  </div>
                ))}
                <p className="rcfg__hint">Để trống = dùng nhãn mặc định. Giá trị động (tên khách, tiền, mã đơn…) tự điền từ đơn.</p>
              </div>
            )}

            {/* Định dạng khối (trừ divider/spacer) */}
            {!['divider', 'spacer'].includes(editBlk.type) && (
              <div className="fmt-controls">
                {editBlk.type === 'custom_text' && (
                  <label className="rcfg__switch"><input type="checkbox" checked={editFmt.title} onChange={(e) => setF('title', e.target.checked)} /><span>Tiêu đề (cỡ lớn nhất · đậm · căn giữa)</span></label>
                )}
                <div className="fmt-row fmt-row--bold">
                  {isField(editBlk.type) ? (
                    <>
                      <label className="rcfg__switch"><input type="checkbox" checked={editFmt.bold_label} onChange={(e) => setF('bold_label', e.target.checked)} /><span>Đậm nhãn</span></label>
                      <label className="rcfg__switch"><input type="checkbox" checked={editFmt.bold_value} onChange={(e) => setF('bold_value', e.target.checked)} /><span>Đậm giá trị</span></label>
                    </>
                  ) : (
                    <label className="rcfg__switch"><input type="checkbox" checked={editFmt.bold} onChange={(e) => setF('bold', e.target.checked)} /><span>In đậm</span></label>
                  )}
                  {canItalic(editBlk.type) && (
                    <label className="rcfg__switch"><input type="checkbox" checked={editFmt.italic} onChange={(e) => setF('italic', e.target.checked)} /><span>In nghiêng</span></label>
                  )}
                </div>
                <div className="fmt-row"><span>Căn lề</span>
                  <div className="seg seg--sm3">
                    {['left', 'center', 'right'].map((a) => (
                      <button key={a} className={`seg__btn ${editFmt.align === a ? 'seg__btn--active' : ''}`} onClick={() => setF('align', a)}>
                        {a === 'left' ? 'Trái' : a === 'center' ? 'Giữa' : 'Phải'}
                      </button>
                    ))}
                  </div>
                </div>
                <div className="fmt-row"><span>Cỡ chữ</span>
                  <div className="seg seg--sm3">
                    {['small', 'normal', 'large'].map((s) => (
                      <button key={s} className={`seg__btn ${editFmt.size === s ? 'seg__btn--active' : ''}`} onClick={() => setF('size', s)}>
                        {s === 'small' ? 'Nhỏ' : s === 'normal' ? 'Vừa' : 'Lớn'}
                      </button>
                    ))}
                  </div>
                </div>
              </div>
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
