import { useEffect, useMemo, useRef, useState } from 'react'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { ApiError, api } from '../lib/api'
import { DEFAULT_LIEN2, blocksToRows, clearReceiptCache, normalizeLien2, normalizeReceipt, rowsToBlocks } from '../lib/receipt'
import Ico from '../components/receipt/Ico'
import BlockEditModal from '../components/receipt/BlockEditModal'
import BlockListEditor from '../components/receipt/BlockListEditor'
import ReceiptEditor from '../components/receipt/ReceiptEditor'
import { Lien2LabelBody } from '../components/Lien2Label'

// Mẫu nhãn liên 2 (Hướng B, Mảnh 2): 6 thành phần bật/tắt + cỡ mã đơn. Mã đơn + số nhãn LUÔN hiện.
const LIEN2_TOGGLES = [
  ['show_customer_name', 'Tên khách'],
  ['show_recv_time', 'Giờ nhận'],
  ['show_pickup_time', 'Giờ giao'],
  ['show_amount', 'Số tiền (khi chưa thanh toán)'],
  ['show_payment_status', 'Trạng thái thanh toán'],
  ['show_note', 'Ghi chú'],
]
// Đơn MẪU cho preview nhãn (không gọi API) — đủ field Lien2LabelBody đọc.
const LIEN2_SAMPLE = {
  order_code: 'TX-0042', payment_status: 'unpaid', customer_name: 'Nguyễn Văn A',
  total_amount: 150000, created_at: '2025-06-20T02:30:00Z', pickup_at: '2025-06-21T09:00:00Z',
  notes: 'Giặt riêng đồ trắng, không dùng nước xả',
}

// Màn TENANT sửa mẫu phiếu. Stage refactor editor: editor/modal/preview tách ra shared
// (components/receipt/) — màn này GIỮ NGUYÊN state + gates (applyConfig/putConfig/buildBcb/
// commonMutate/bcMutate) → payload PUT /settings/receipt BẤT BIẾN. Chỉ thay JSX bằng
// <ReceiptEditor> (khối CHUNG + preview) + slot tenant (branch_contact / auto_print / iframe /
// save / mẫu mặc định). branch_contact tự render = BlockListEditor + BlockEditModal shared.
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
  const [autoPrint, setAutoPrint] = useState(true) // tự in BILL sau khi tạo đơn (6.8.2)
  const [autoPrintCopy2, setAutoPrintCopy2] = useState(true) // tự in LIÊN 2 — TÁCH RIÊNG
  const [autoSaving, setAutoSaving] = useState(false)
  const [copied, setCopied] = useState(false) // feedback copy snippet iframe
  const [uploading, setUploading] = useState(false)
  const [commonEditing, setCommonEditing] = useState(null) // {ri,ci} khối CHUNG đang sửa
  const [bcEditing, setBcEditing] = useState(null)         // {ri,ci} khối CN đang sửa
  const [restoredMsg, setRestoredMsg] = useState('')       // nhắc "đã nạp mẫu — bấm Lưu"
  const [lien2Cfg, setLien2Cfg] = useState(null)           // mẫu nhãn liên 2 (form RIÊNG, không builder)
  const [lien2Saving, setLien2Saving] = useState(false)
  const [lien2Saved, setLien2Saved] = useState(false)
  const fileRef = useRef(null)

  const applyConfig = (c) => {
    const n = normalizeReceipt(c)
    setBilingual(n.bilingual)
    setLogoUrl(n.logo_url)
    setTrackBaseUrl(n.track_base_url)
    setRows(blocksToRows(n.blocks))
    setLien2Cfg(normalizeLien2(c?.lien2))
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
      .then((s) => {
        setAutoPrint(s.auto_print_receipt !== false)
        setAutoPrintCopy2(s.auto_print_copy2 !== false)
      })
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

  // Lưu NGAY cờ tự-in LIÊN 2 (TÁCH RIÊNG bill). Optimistic + revert nếu lỗi.
  const saveAutoPrintCopy2 = async (next) => {
    if (autoSaving) return
    setAutoPrintCopy2(next)
    setAutoSaving(true)
    setError('')
    try {
      await api.put('/settings', { auto_print_copy2: next })
    } catch (e) {
      setAutoPrintCopy2(!next)
      setError(e?.message || 'Không lưu được tùy chọn tự in liên 2')
    } finally {
      setAutoSaving(false)
    }
  }

  // Snippet iframe nhúng (Lớp 3) — slug THẬT điền sẵn; tenant dán vào web họ.
  const embedSnippet = (
    '<iframe id="gt-track" src="https://track.giatui.app/embed/' + (user?.tenant_slug || '') + '"' +
    ' style="width:100%;border:0;min-height:480px"></iframe>\n' +
    '<script>var c=new URLSearchParams(location.search).get("code");' +
    ' if(c) document.getElementById("gt-track").src=' +
    '"https://track.giatui.app/embed/' + (user?.tenant_slug || '') + '?code="+encodeURIComponent(c);</script>'
  )
  const copySnippet = async () => {
    try {
      await navigator.clipboard.writeText(embedSnippet)
      setCopied(true)
      setTimeout(() => setCopied(false), 2000)
    } catch {
      /* clipboard không khả dụng — bỏ qua */
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
      clearReceiptCache(); setSaved(true); setRestoredMsg('')
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? 'Chỉ owner mới lưu được mẫu phiếu.' : e?.message || 'Không lưu được cấu hình')
    } finally { setSaving(false) }
  }

  // ── Mẫu nhãn LIÊN 2 (form RIÊNG, không builder) ────────────────────────────────────────────
  const setLien2Field = (k, v) => { setLien2Saved(false); setLien2Cfg((c) => ({ ...c, [k]: v })) }
  const resetLien2 = () => { setLien2Saved(false); setLien2Cfg({ ...DEFAULT_LIEN2 }) }
  // ⚠️ GIỮ NGUYÊN phần bill: GET config server HIỆN TẠI → gửi lại y nguyên blocks/branch_contact +
  // CHỈ thay key lien2. Độc lập với editor bill (kể cả khi owner đang sửa bill chưa lưu) → lưu nhãn
  // KHÔNG đụng config bill. (BE Mảnh 1: data.lien2 có → lưu; còn blocks PHẢI gửi đủ kẻo bị về rỗng.)
  const saveLien2 = async () => {
    if (lien2Saving || !lien2Cfg) return
    setLien2Saving(true); setError('')
    try {
      const cur = await api.get('/settings/receipt')
      await api.put('/settings/receipt', {
        bilingual: cur.bilingual !== false,
        track_base_url: cur.track_base_url || '',
        blocks: cur.blocks || [],
        branch_contact_blocks: cur.branch_contact_blocks || {},
        lien2: lien2Cfg,
      })
      clearReceiptCache(); setLien2Saved(true)
    } catch (e) {
      setError(e instanceof ApiError && e.status === 403 ? 'Chỉ owner mới sửa được mẫu nhãn.' : e?.message || 'Không lưu được mẫu nhãn liên 2')
    } finally { setLien2Saving(false) }
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

  // Khôi phục LOAD-ONLY: nạp mẫu vào trình sửa, KHÔNG tự lưu (owner bấm "Lưu mẫu in" mới áp).
  // applyConfig(cfg) đổ vào editor; setSaved(false) → đánh dấu chưa lưu; restoredMsg nhắc owner.
  const loadInto = async (fetcher, okMsg, failMsg, confirmMsg) => {
    if (!window.confirm(confirmMsg)) return
    setError(''); setRestoredMsg('')
    try {
      applyConfig(await fetcher())
      setSaved(false)
      setRestoredMsg(okMsg)
    } catch (e) {
      setError(e?.message || failMsg)
    }
  }
  const restoreMine = () => loadInto(
    api.getMyDefaultReceipt, 'Đã nạp MẪU CỦA TÔI — bấm "Lưu mẫu in" để áp.',
    'Không nạp được mẫu của tôi',
    'Nạp lại MẪU CỦA TÔI vào trình sửa? Cấu hình đang chỉnh sẽ bị thay — bấm Lưu mẫu in mới áp.',
  )
  const restoreSystem = () => loadInto(
    api.getSystemDefaultReceipt, 'Đã nạp MẪU GỐC HỆ THỐNG — bấm "Lưu mẫu in" để áp.',
    'Không nạp được mẫu hệ thống',
    'Nạp lại MẪU GỐC HỆ THỐNG (Super Admin) vào trình sửa? Cấu hình đang chỉnh sẽ bị thay — bấm Lưu mẫu in mới áp.',
  )

  const previewConfig = useMemo(
    () => (rows ? {
      bilingual, logo_url: logoUrl, track_base_url: trackBaseUrl,
      blocks: rowsToBlocks(rows),
      // Chỉ đổ bộ khối của CN đang xem trước → khu cuối hiện đúng CN đó.
      branch_contact_blocks: previewCn ? { [previewCn]: rowsToBlocks(bcRowsByBranch[previewCn] || []) } : {},
    } : null),
    [rows, bilingual, logoUrl, trackBaseUrl, previewCn, bcRowsByBranch],
  )

  if (!rows) return <p className="shift__hint">{error || 'Đang tải cấu hình phiếu…'}</p>

  // Phần GẮN TENANT trong card "Tùy chọn chung" (iframe nhúng + tự-in) — chèn qua optionsExtra.
  const optionsExtra = (
    <>
      {/* Khối mã nhúng iframe — tenant có web tự nhúng trang tra cứu (Lớp 3) */}
      <label className="field" style={{ marginTop: 12 }}>
        <span>Mã nhúng (iframe) cho web của bạn</span>
        <textarea className="input" readOnly rows={5} value={embedSnippet}
          style={{ fontFamily: 'monospace', fontSize: 12, resize: 'vertical' }}
          onFocus={(e) => e.target.select()} />
      </label>
      <div style={{ display: 'flex', alignItems: 'center', gap: 10, marginBottom: 8 }}>
        <button type="button" className="btn btn--ghost btn--sm" onClick={copySnippet}>
          {copied ? 'Đã copy ✓' : 'Copy'}
        </button>
        <span className="rcfg__hint" style={{ margin: 0 }}>
          Dán đoạn này vào trang web của bạn (nếu có web riêng để tra cứu).
        </span>
      </div>

      <label className="rcfg__switch rcfg__switch--row">
        <input type="checkbox" checked={autoPrint} disabled={!canEdit || autoSaving}
          onChange={(e) => saveAutoPrint(e.target.checked)} />
        <span>Tự động in phiếu sau khi tạo đơn</span>
      </label>
      <p className="rcfg__hint">
        Bật: tạo đơn xong tự in phiếu ngay. Tắt: không tự in — nhân viên bấm “In phiếu” khi khách cần lấy bill.
      </p>

      <label className="rcfg__switch rcfg__switch--row">
        <input type="checkbox" checked={autoPrintCopy2} disabled={!canEdit || autoSaving}
          onChange={(e) => saveAutoPrintCopy2(e.target.checked)} />
        <span>Tự động in liên 2 khi tạo đơn</span>
      </label>
      <p className="rcfg__hint">
        Bật: tạo đơn xong tự in nhãn dán túi (liên 2). Tách riêng với in phiếu — bật/tắt độc lập.
      </p>
    </>
  )

  // Phần GẮN TENANT trong cột editor (sau card khối): liên hệ theo CN + lưu + mẫu mặc định.
  const tenantSections = (
    <>
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
                onOpenEdit={(_, ri, ci) => setBcEditing({ ri, ci })}
              />
            )}
          </>
        )}
      </div>

      {error && !commonEditing && !bcEditing && <div className="alert alert--error">{error}</div>}
      {canEdit && (
        <button className="btn btn--primary btn--xl btn--block" onClick={save} disabled={saving}>
          {saving ? 'Đang lưu…' : saved ? <><Ico name="check" /> Đã lưu</> : 'Lưu mẫu phiếu'}
        </button>
      )}

      {canEdit && (
        <div className="shift__card rcfg__default">
          <h3 className="card__title">Mẫu mặc định</h3>
          <p className="rcfg__hint">
            {hasDefault
              ? 'Đã lưu mẫu riêng của tiệm. "Khôi phục mẫu của tôi" nạp lại mẫu đó.'
              : 'Chưa lưu mẫu riêng. Có thể nạp lại "Mẫu gốc hệ thống" (Super Admin) để bắt đầu.'}
            {' '}Nạp xong KHÔNG tự lưu — bấm <strong>Lưu mẫu in</strong> để áp.
          </p>
          {restoredMsg && <div className="alert alert--success">{restoredMsg}</div>}
          <div className="rcfg__default-btns">
            <button className="btn btn--ghost btn--lg" onClick={saveAsDefault} disabled={saving}>
              Lưu làm mẫu của tôi
            </button>
            {hasDefault && (
              <button className="btn btn--ghost btn--lg" onClick={restoreMine} disabled={saving}>
                Khôi phục mẫu của tôi
              </button>
            )}
            <button className="btn btn--ghost btn--lg" onClick={restoreSystem} disabled={saving}>
              Khôi phục mẫu gốc hệ thống
            </button>
          </div>
        </div>
      )}

      {/* ── MẪU NHÃN LIÊN 2 (dán túi) — form RIÊNG, KHÔNG builder bill. Lưu độc lập, GIỮ config bill. */}
      {lien2Cfg && (
        <div className="shift__card rcfg__lien2">
          <h3 className="card__title">Mẫu nhãn liên 2 (dán túi)</h3>
          <p className="rcfg__hint">
            Chọn thành phần hiện trên nhãn dán túi và cỡ chữ mã đơn.{' '}
            <strong>Mã đơn và số nhãn luôn hiển thị</strong> (không tắt được).
          </p>

          {LIEN2_TOGGLES.map(([k, label]) => (
            <label key={k} className="rcfg__switch rcfg__switch--row">
              <input type="checkbox" checked={!!lien2Cfg[k]} disabled={!canEdit}
                onChange={(e) => setLien2Field(k, e.target.checked)} />
              <span>{label}</span>
            </label>
          ))}

          <label className="field" style={{ marginTop: 12 }}>
            <span>Cỡ chữ mã đơn</span>
            <select className="input" value={lien2Cfg.code_size} disabled={!canEdit}
              onChange={(e) => setLien2Field('code_size', e.target.value)}>
              <option value="small">Nhỏ (S)</option>
              <option value="normal">Vừa (M)</option>
              <option value="large">Lớn (L)</option>
            </select>
          </label>

          {/* Dòng thông tin thêm (Phần B) — bật + nhập SĐT/địa chỉ. Mặc định TẮT. */}
          <label className="rcfg__switch rcfg__switch--row" style={{ marginTop: 12 }}>
            <input type="checkbox" checked={!!lien2Cfg.show_footer_text} disabled={!canEdit}
              onChange={(e) => setLien2Field('show_footer_text', e.target.checked)} />
            <span>Hiện dòng thông tin thêm (cuối nhãn)</span>
          </label>
          <label className="field">
            <span>Nội dung dòng thông tin thêm</span>
            <textarea className="input" rows={2} maxLength={200}
              value={lien2Cfg.footer_text || ''} disabled={!canEdit}
              placeholder="VD: Hotline 0900 000 000 · 12 Lê Lợi, Q1"
              onChange={(e) => setLien2Field('footer_text', e.target.value)} />
          </label>

          {/* Xem trước (đơn mẫu) — đổi theo cấu hình đang chọn. Số nhãn 1/2 minh hoạ luôn-hiện. */}
          <div className="rcfg__lien2-preview-wrap">
            <span className="rcfg__hint" style={{ margin: 0 }}>Xem trước</span>
            <div className="rcfg__lien2-preview">
              <Lien2LabelBody order={LIEN2_SAMPLE} seq={{ n: 1, total: 2 }} cfg={lien2Cfg} />
            </div>
          </div>

          {lien2Saved && <div className="alert alert--success">Đã lưu mẫu nhãn liên 2.</div>}
          {canEdit && (
            <div className="rcfg__default-btns">
              <button className="btn btn--primary btn--lg" onClick={saveLien2} disabled={lien2Saving}>
                {lien2Saving ? 'Đang lưu…' : lien2Saved ? <><Ico name="check" /> Đã lưu nhãn</> : 'Lưu mẫu nhãn'}
              </button>
              <button className="btn btn--ghost btn--lg" onClick={resetLien2} disabled={lien2Saving}>
                Khôi phục mặc định
              </button>
            </div>
          )}
        </div>
      )}
    </>
  )

  return (
    <>
      <ReceiptEditor
        title="Mẫu phiếu in — bố cục theo khối"
        canEdit={canEdit}
        readOnlyHint="Chỉ chủ chuỗi (owner) mới sửa được. Bạn đang xem."
        bilingual={bilingual} onBilingual={(v) => { dirty(); setBilingual(v) }}
        trackBaseUrl={trackBaseUrl} onTrackBaseUrl={(v) => { dirty(); setTrackBaseUrl(v) }}
        rows={rows} mutateRows={commonMutate}
        editing={commonEditing} onEditing={setCommonEditing}
        logoUrl={logoUrl} onUploadLogo={onPickLogo} uploading={uploading} fileRef={fileRef}
        slug={user?.tenant_slug}
        preview={{ config: previewConfig, branches, previewCn, onPreviewCn: setPreviewCn }}
        optionsExtra={optionsExtra}
      >
        {tenantSections}
      </ReceiptEditor>

      {/* Modal sửa khối CN (branch_contact) — overlay fixed, render ngoài rcfg cũng đúng vị trí. */}
      {bcEditing && editCn && (bcRowsByBranch[editCn] || [])[bcEditing.ri] && (
        <BlockEditModal
          key={`bc-${editCn}-${bcEditing.ri}-${bcEditing.ci}`}
          block={bcRowsByBranch[editCn][bcEditing.ri][bcEditing.ci]}
          bilingual={bilingual}
          canEdit={canEdit}
          logoUrl={logoUrl}
          onUploadLogo={onPickLogo}
          uploading={uploading}
          fileRef={fileRef}
          onSave={(f) => {
            bcMutate(editCn)((rs) => { rs[bcEditing.ri][bcEditing.ci] = { ...rs[bcEditing.ri][bcEditing.ci], ...f }; return rs })
            setBcEditing(null)
          }}
          onClose={() => setBcEditing(null)}
        />
      )}
    </>
  )
}
