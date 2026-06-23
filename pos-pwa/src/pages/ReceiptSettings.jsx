import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import BillContent from '../components/Bill'
import { ApiError, api } from '../lib/api'
import {
  ADDABLE,
  BLOCK_LABELS,
  BLOCK_META,
  BLOCK_VALUES,
  blockListLabel,
  blocksToRows,
  canItalic,
  clearReceiptCache,
  defaultAlign,
  isField,
  normalizeReceipt,
  removeCellFromRows,
  rowsToBlocks,
} from '../lib/receipt'

// Demo cho preview builder: KHÔNG đặt surcharge_reason/discount_reason để preview
// giữ nhãn chung "Phụ thu"/"Giảm giá" (tên chiến dịch chỉ hiện ở bill IN THẬT).
const SAMPLE_ORDER = {
  order_code: 'B1-00042',
  subtotal: 185000, surcharge_amount: 18500, discount_amount: 15000,
  total_amount: 188500, payment_status: 'paid',
  pickup_at: '2026-06-14T03:30:00Z', created_at: '2026-06-13T09:15:00Z',
  customer_name: 'Chị Lan', customer_phone: '0905 123 456',
  // branch_id gán động ở preview (= CN đang xem) → khu "Liên hệ theo CN" hiện đúng.
  items: [
    { id: 1, service_name: 'Giặt sấy (≤3kg)', quantity: 1, unit_price: 60000, subtotal: 60000 },
    { id: 2, service_name: 'Áo Vest', quantity: 2, unit_price: 60000, subtotal: 120000 },
    { id: 3, service_name: 'Giặt thường', quantity: 1, unit_price: 5000, subtotal: 5000 },
  ],
}

// Icon inline SVG (6.69) — thay glyph ✎⧉🗑↑↓⊞✓ (KHÔNG webfont/emoji).
const RICONS = {
  edit: 'M4 20h3.5L17 9.5a2.1 2.1 0 0 0-3-3L3.5 17z M12.5 8l3 3',
  copy: 'M9 9h9v9H9z M5 14V6a1 1 0 0 1 1-1h8',
  trash: 'M4 7h16 M9 7V5h6v2 M6 7l1 13h10l1-13 M10 11v5 M14 11v5',
  up: 'M12 19V6 M6 12l6-6 6 6',
  down: 'M12 5v13 M6 12l6 6 6-6',
  merge: 'M5 5h6v6H5z M13 13h6v6h-6z M11 8h5v5',
  check: 'M20 6L9 17l-5-5',
}
function Ico({ name }) {
  return (
    <svg className="ic-btn" viewBox="0 0 24 24" fill="none" stroke="currentColor"
      strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true">
      <path d={RICONS[name]} />
    </svg>
  )
}

// Trình sửa DANH SÁCH khối (list + thêm + sắp xếp/ghép/tách + kéo-thả) — DÙNG LẠI
// cho cả khối CHUNG lẫn từng CN (khu "Liên hệ theo chi nhánh"). Mỗi instance giữ
// dragRi riêng (kéo-thả không lẫn giữa 2 khu). Sửa nội dung 1 khối → gọi
// onOpenEdit(scopeKey, ri, ci) lên cha (modal dùng chung). mutate(fn): cha truyền
// hàm áp đổi vào ĐÚNG mảng theo scope (đã đánh dấu dirty + slice sẵn).
function BlockListEditor({ rows, mutate, canEdit, scopeKey, onOpenEdit }) {
  const [dragRi, setDragRi] = useState(null)

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
  const removeBlock = (ri, ci) => mutate((rs) => removeCellFromRows(rs, ri, ci))
  const copyBlock = (ri, ci) => mutate((rs) => {
    const src = rs[ri][ci]
    const clone = {
      ...src, id: `${src.type}_${Date.now()}`, col: 'full', enabled: true,
      removable: true, content: { ...(src.content || {}) },
    }
    rs.splice(ri + 1, 0, [clone])
    return rs
  })
  const addBlock = (type) => mutate((rs) => {
    const id = `${type}_${Date.now()}`
    const content = type === 'custom_text' ? { vi: 'Nội dung tự do…', en: 'Custom text…' }
      : type === 'divider' ? { style: 'dashed' }
        : type === 'spacer' ? { height: 'small' } : {}
    rs.push([{ id, type, enabled: true, row: rs.length, col: 'full', bold: false, italic: false, title: false, align: null, size: 'normal', removable: true, content }])
    return rs
  })
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
    return rs.map((r, i) => (i === ti ? [r[0], dragged] : r)).filter((_, i) => i !== di)
  })
  const draggedSingle = dragRi != null && rows[dragRi]?.length === 1

  return (
    <>
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
                    <button className="icon-btn" disabled={!canEdit} title="Sửa nhãn / nội dung / định dạng" onClick={() => onOpenEdit(scopeKey, ri, ci)}><Ico name="edit" /></button>
                    <button className="icon-btn" disabled={!canEdit} title="Nhân bản khối" onClick={() => copyBlock(ri, ci)}><Ico name="copy" /></button>
                    {blk.removable && (
                      <button className="icon-btn" disabled={!canEdit} title="Xóa khối" onClick={() => removeBlock(ri, ci)}><Ico name="trash" /></button>
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
              <button className="icon-btn" disabled={!canEdit || ri === 0} title="Lên" onClick={() => moveRow(ri, -1)}><Ico name="up" /></button>
              <button className="icon-btn" disabled={!canEdit || ri === rows.length - 1} title="Xuống" onClick={() => moveRow(ri, +1)}><Ico name="down" /></button>
              {row.length === 1 && canPairDown(ri) && (
                <button className="icon-btn icon-btn--wide" disabled={!canEdit} title="Ghép với hàng dưới" onClick={() => pairDown(ri)}><Ico name="merge" /></button>
              )}
              {row.length === 2 && (
                <button className="icon-btn icon-btn--wide" disabled={!canEdit} title="Tách thành 2 hàng" onClick={() => splitRow(ri)}>⊟</button>
              )}
            </div>
          </div>
        ))}
        {rows.length === 0 && <p className="rcfg__hint">Chưa có khối nào — bấm thêm bên dưới.</p>}
      </div>
      {canEdit && (
        <div className="bld-add">
          {ADDABLE.map((a) => (
            <button key={a.type} className="btn btn--ghost btn--sm" onClick={() => addBlock(a.type)}>{a.label}</button>
          ))}
        </div>
      )}
    </>
  )
}

export default function ReceiptSettings() {
  const { user } = useAuth()
  const { branches } = useBranch() // owner: list CN active (sẵn) — cho khu "Liên hệ theo CN"
  const canEdit = user?.role === 'owner'

  const [bilingual, setBilingual] = useState(true)
  const [logoUrl, setLogoUrl] = useState('')
  const [trackBaseUrl, setTrackBaseUrl] = useState('')
  const [rows, setRows] = useState(null)                 // khối CHUNG
  const [bcRowsByBranch, setBcRowsByBranch] = useState({}) // {branch_id: rows[]} theo CN
  const [editCn, setEditCn] = useState(null)             // CN đang soạn ở khu liên hệ
  const [previewCn, setPreviewCn] = useState(null)       // CN đang xem trước
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [hasDefault, setHasDefault] = useState(false) // mẫu mặc định tenant đã lưu?
  const [autoPrint, setAutoPrint] = useState(true) // tự in sau khi tạo đơn (6.8.2)
  const [autoSaving, setAutoSaving] = useState(false)

  const [editBlk, setEditBlk] = useState(null) // {scope, ri, ci, type}; scope=null → khối chung
  const [editContent, setEditContent] = useState({})
  const [editFmt, setEditFmt] = useState({ bold: false, align: 'left', size: 'normal' })
  const [uploading, setUploading] = useState(false)
  const fileRef = useRef(null)

  const applyConfig = (c) => {
    const n = normalizeReceipt(c)
    setBilingual(n.bilingual)
    setLogoUrl(n.logo_url)
    setTrackBaseUrl(n.track_base_url)
    setRows(blocksToRows(n.blocks))
    // branch_contact_blocks (map branch_id → mảng khối) → rows theo CN.
    const bcb = c?.branch_contact_blocks || {}
    setBcRowsByBranch(Object.fromEntries(
      Object.entries(bcb).map(([bid, blks]) => [bid, blocksToRows(blks || [])]),
    ))
  }

  useEffect(() => {
    api.get('/settings/receipt')
      .then(applyConfig)
      .catch((e) => setError(e?.message || 'Không tải được cấu hình phiếu'))
    api.get('/settings/receipt/status')
      .then((s) => setHasDefault(!!s.has_tenant_default))
      .catch(() => {})
    api.get('/settings/pos')
      .then((s) => setAutoPrint(s.auto_print_receipt !== false))
      .catch(() => {})
  }, [])

  // Mặc định chọn CN đầu cho khu soạn + preview khi danh sách CN đã nạp.
  useEffect(() => {
    if (branches.length === 0) return
    setEditCn((cur) => cur || branches[0].id)
    setPreviewCn((cur) => cur || branches[0].id)
  }, [branches])

  // Lưu NGAY cờ tự-in (PUT /settings, owner). Optimistic + revert nếu lỗi.
  const saveAutoPrint = async (next) => {
    if (autoSaving) return
    setAutoPrint(next)
    setAutoSaving(true)
    setError('')
    try {
      await api.put('/settings', { auto_print_receipt: next })
    } catch (e) {
      setAutoPrint(!next)
      setError(e?.message || 'Không lưu được tùy chọn tự in')
    } finally {
      setAutoSaving(false)
    }
  }

  const dirty = () => setSaved(false)
  // Áp hàm đổi vào ĐÚNG mảng theo scope (null = khối chung; else = CN). Slice sẵn +
  // đánh dấu dirty để BlockListEditor chỉ cần trả mảng mới.
  const commonMutate = (fn) => { dirty(); setRows((rs) => fn(rs.map((r) => r.slice()))) }
  const bcMutate = (bid) => (fn) => {
    dirty()
    setBcRowsByBranch((m) => ({ ...m, [bid]: fn((m[bid] || []).map((r) => r.slice())) }))
  }
  const rowsForScope = (scope) => (scope == null ? rows : (bcRowsByBranch[scope] || []))
  const mutateForScope = (scope) => (scope == null ? commonMutate : bcMutate(scope))

  const openEdit = (scope, ri, ci) => {
    const b = rowsForScope(scope)[ri][ci]
    setEditBlk({ scope, ri, ci, type: b.type })
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
    const { scope, ri, ci } = editBlk
    mutateForScope(scope)((rs) => {
      rs[ri][ci] = { ...rs[ri][ci], content: { ...editContent }, ...editFmt }
      return rs
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

  // branch_contact_blocks gửi PUT: map branch_id → mảng khối (rowsToBlocks). CN có
  // mảng rỗng vẫn gửi {} entry — BE migrate ra rỗng, không sao.
  const buildBcb = () => Object.fromEntries(
    Object.entries(bcRowsByBranch).map(([bid, rws]) => [bid, rowsToBlocks(rws)]),
  )
  const putConfig = () => api.put('/settings/receipt', {
    bilingual, track_base_url: trackBaseUrl.trim(),
    blocks: rowsToBlocks(rows), branch_contact_blocks: buildBcb(),
  })

  const save = async () => {
    setSaving(true); setError('')
    try {
      await putConfig()
      clearReceiptCache(); setSaved(true)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? 'Chỉ owner mới lưu được mẫu phiếu.' : e?.message || 'Không lưu được cấu hình')
    } finally { setSaving(false) }
  }

  // Lưu cấu hình ĐANG DÙNG làm mẫu mặc định của tenant (lưu active trước, rồi promote).
  const saveAsDefault = async () => {
    if (!window.confirm('Lưu cấu hình hiện tại làm MẪU MẶC ĐỊNH của tiệm? (dùng cho nút Khôi phục sau này)')) return
    setSaving(true); setError('')
    try {
      await putConfig()
      await api.post('/settings/receipt/save-default')
      clearReceiptCache(); setHasDefault(true); setSaved(true)
    } catch (e) {
      setError(e?.message || 'Không lưu được mẫu mặc định')
    } finally { setSaving(false) }
  }

  // Khôi phục về mẫu mặc định tenant (hoặc mẫu gốc nền tảng nếu chưa lưu).
  const restoreDefault = async () => {
    const msg = hasDefault
      ? 'Khôi phục về MẪU MẶC ĐỊNH của tiệm? Cấu hình đang chỉnh sẽ bị thay thế — KHÔNG hoàn tác.'
      : 'Chưa lưu mẫu mặc định riêng. Khôi phục sẽ về MẪU GỐC NỀN TẢNG (có placeholder) — KHÔNG hoàn tác. Tiếp tục?'
    if (!window.confirm(msg)) return
    setSaving(true); setError('')
    try {
      const cfg = await api.post('/settings/receipt/restore-default')
      applyConfig(cfg); clearReceiptCache(); setSaved(true)
    } catch (e) {
      setError(e?.message || 'Không khôi phục được')
    } finally { setSaving(false) }
  }

  const previewConfig = useMemo(
    () => (rows ? {
      bilingual, logo_url: logoUrl, track_base_url: trackBaseUrl,
      blocks: rowsToBlocks(rows),
      // Chỉ đổ bộ khối của CN đang xem trước → khu cuối hiện đúng CN đó.
      branch_contact_blocks: previewCn ? { [previewCn]: rowsToBlocks(bcRowsByBranch[previewCn] || []) } : {},
    } : null),
    [rows, bilingual, logoUrl, trackBaseUrl, previewCn, bcRowsByBranch],
  )
  const previewOrder = useMemo(() => ({ ...SAMPLE_ORDER, branch_id: previewCn }), [previewCn])

  if (!rows) return <p className="shift__hint">{error || 'Đang tải cấu hình phiếu…'}</p>

  return (
    <div className="rcfg">
      <div className="rcfg__editor">
        <h2 className="services__title">Mẫu phiếu in — bố cục theo khối</h2>
        {!canEdit && <div className="alert alert--error">Chỉ chủ chuỗi (owner) mới sửa được. Bạn đang xem.</div>}

        <div className="shift__card">
          <div className="rcfg__card-head">
            <h3 className="card__title">Tùy chọn chung</h3>
            <label className="rcfg__switch">
              <input type="checkbox" checked={bilingual} disabled={!canEdit} onChange={(e) => { dirty(); setBilingual(e.target.checked) }} />
              <span>Hiện tiếng Anh</span>
            </label>
          </div>
          <p className="rcfg__hint">
            Kéo-thả (hoặc nút Lên/Xuống) để sắp xếp. Kéo 1 khối thả vào ô <strong>＋ghép</strong> của khối khác,
            hoặc nút <strong>Ghép/Tách</strong>, để xếp 2 khối/hàng (tự do, không giới hạn).
            Bấm nút sửa để sửa nhãn, nội dung &amp; định dạng (đậm · nghiêng · căn lề · cỡ chữ).
          </p>
          <label className="field">
            <span>Link tra cứu cho QR (base URL + mã đơn)</span>
            <input className="input" type="text" value={trackBaseUrl} disabled={!canEdit}
              placeholder="https://track.giatui.app/track/"
              onChange={(e) => { dirty(); setTrackBaseUrl(e.target.value) }} />
          </label>
          <p className="rcfg__hint">Để trống = dùng mặc định track.giatui.app. QR = link này + mã đơn.</p>

          <label className="rcfg__switch rcfg__switch--row">
            <input type="checkbox" checked={autoPrint} disabled={!canEdit || autoSaving}
              onChange={(e) => saveAutoPrint(e.target.checked)} />
            <span>Tự động in phiếu sau khi tạo đơn</span>
          </label>
          <p className="rcfg__hint">
            Bật: tạo đơn xong tự in phiếu ngay. Tắt: không tự in — nhân viên bấm “In phiếu” khi khách cần lấy bill.
          </p>
        </div>

        <div className="shift__card">
          <h3 className="card__title">Các khối trên phiếu</h3>
          <BlockListEditor rows={rows} mutate={commonMutate} canEdit={canEdit} scopeKey={null} onOpenEdit={openEdit} />
        </div>

        {/* Khu liên hệ theo chi nhánh — IN CUỐI bill, mỗi CN một bộ khối riêng. */}
        <div className="shift__card">
          <h3 className="card__title">Liên hệ theo chi nhánh (in cuối bill)</h3>
          <p className="rcfg__hint">
            Mỗi chi nhánh một bộ khối riêng (địa chỉ · SĐT… — khối thật, đầy đủ định dạng).
            Bill chỉ in bộ của chi nhánh tạo đơn. CN chưa soạn → không in phần này.
          </p>
          {branches.length === 0 ? (
            <p className="rcfg__hint">Chưa có chi nhánh nào (active).</p>
          ) : (
            <>
              <label className="field">
                <span>Soạn cho chi nhánh</span>
                <select className="input" value={editCn || ''} disabled={!canEdit}
                  onChange={(e) => setEditCn(e.target.value)}>
                  {branches.map((b) => (
                    <option key={b.id} value={b.id}>{b.order_prefix} · {b.name}</option>
                  ))}
                </select>
              </label>
              {editCn && (
                <BlockListEditor
                  rows={bcRowsByBranch[editCn] || []}
                  mutate={bcMutate(editCn)}
                  canEdit={canEdit}
                  scopeKey={editCn}
                  onOpenEdit={openEdit}
                />
              )}
            </>
          )}
        </div>

        {error && !editBlk && <div className="alert alert--error">{error}</div>}
        {canEdit && (
          <button className="btn btn--primary btn--xl btn--block" onClick={save} disabled={saving}>
            {saving ? 'Đang lưu…' : saved ? <><Ico name="check" /> Đã lưu</> : 'Lưu mẫu phiếu'}
          </button>
        )}

        {canEdit && (
          <div className="shift__card rcfg__default">
            <h3 className="card__title">Mẫu mặc định của tiệm</h3>
            <p className="rcfg__hint">
              Trạng thái: <strong>Đang chỉnh sửa</strong> →
              {hasDefault
                ? ' có mẫu mặc định riêng đã lưu (Khôi phục sẽ về mẫu này).'
                : ' chưa lưu mẫu riêng → Khôi phục dùng mẫu gốc nền tảng.'}
            </p>
            <div className="rcfg__default-btns">
              <button className="btn btn--ghost btn--lg" onClick={saveAsDefault} disabled={saving}>
                Lưu làm mẫu mặc định của tôi
              </button>
              <button className="btn btn--ghost btn--lg" onClick={restoreDefault} disabled={saving}>
                Khôi phục mẫu mặc định
              </button>
            </div>
          </div>
        )}
      </div>

      <div className="rcfg__preview">
        <div className="rcfg__preview-label">Xem trước (khổ 80mm)</div>
        {branches.length > 0 && (
          <label className="field rcfg__preview-cn">
            <span>Xem theo chi nhánh</span>
            <select className="input" value={previewCn || ''} onChange={(e) => setPreviewCn(e.target.value)}>
              {branches.map((b) => (
                <option key={b.id} value={b.id}>{b.order_prefix} · {b.name}</option>
              ))}
            </select>
          </label>
        )}
        <div className="rcp-preview">
          <BillContent config={previewConfig} order={previewOrder} />
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
