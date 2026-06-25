import { useCallback, useEffect, useRef, useState } from 'react'
import { api } from '../../lib/api'
import { blocksToRows, normalizeReceipt, rowsToBlocks } from '../../lib/receipt'
import ReceiptEditor from '../../components/receipt/ReceiptEditor'

// Editor mẫu in CHUẨN system-wide (Super Admin) — Bước 2: dùng ReceiptEditor shared (đầy đủ
// khối + định dạng + preview như tenant). Flags-off phần per-tenant: KHÔNG branch_contact
// (branches=[]), KHÔNG logo upload (onUploadLogo undefined → khối logo giữ làm placeholder),
// KHÔNG auto_print/iframe. slug="{slug}" placeholder cho QR preview. BE PUT đã strip
// branch_contact_blocks/logo_url → mẫu chuẩn chỉ phần CHUNG.
export default function AdminDefaultReceipt() {
  const [bilingual, setBilingual] = useState(true)
  const [trackBase, setTrackBase] = useState('')
  const [rows, setRows] = useState(null)
  const [editing, setEditing] = useState(null) // {ri,ci} khối đang sửa
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const fileRef = useRef(null)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const c = normalizeReceipt(await api.admin.getDefaultReceipt())
      setBilingual(c.bilingual !== false)
      setTrackBase(c.track_base_url || '')
      setRows(blocksToRows(c.blocks || []))
    } catch (e) {
      setError(e?.message || 'Không tải được mẫu in')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    load()
  }, [load])

  const dirty = () => setSaved(false)
  const mutate = (fn) => { dirty(); setRows((rs) => fn(rs.map((r) => r.slice()))) }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      // BE strip branch_contact_blocks/logo_url → chỉ giữ blocks + bilingual + track_base_url.
      await api.admin.setDefaultReceipt({
        bilingual, track_base_url: trackBase.trim(), blocks: rowsToBlocks(rows),
      })
      setSaved(true)
    } catch (e) {
      setError(e?.message || 'Không lưu được mẫu chuẩn')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="shift__hint">Đang tải…</p>
  if (rows === null) return <div className="alert alert--error">{error || 'Lỗi'}</div>

  const previewConfig = {
    bilingual, logo_url: '', track_base_url: trackBase,
    blocks: rowsToBlocks(rows), branch_contact_blocks: {},
  }

  return (
    <ReceiptEditor
      title="Mẫu in mặc định"
      canEdit
      bilingual={bilingual} onBilingual={(v) => { dirty(); setBilingual(v) }}
      trackBaseUrl={trackBase} onTrackBaseUrl={(v) => { dirty(); setTrackBase(v) }}
      rows={rows} mutateRows={mutate}
      editing={editing} onEditing={setEditing}
      logoUrl="" uploading={false} fileRef={fileRef}
      slug="{slug}"
      preview={{ config: previewConfig, branches: [], previewCn: null, onPreviewCn: () => {} }}
    >
      {/* Phần riêng admin (cột editor, sau khối): mô tả + lưu. KHÔNG branch_contact/auto_print. */}
      <div className="shift__card">
        <p className="shift__hint" style={{ margin: 0 }}>
          Mẫu chuẩn áp cho <strong>cửa hàng tạo MỚI</strong> (copy vào cấu hình của họ). Cửa hàng
          đang có KHÔNG đổi. Logo, liên hệ chi nhánh, tự động in… do từng cửa hàng tự đặt sau.
        </p>
      </div>
      {error && <div className="alert alert--error">{error}</div>}
      {saved && <div className="alert alert--success">Đã lưu mẫu chuẩn.</div>}
      <button className="btn btn--primary btn--xl btn--block" onClick={save} disabled={saving}>
        {saving ? 'Đang lưu…' : 'Lưu mẫu chuẩn'}
      </button>
    </ReceiptEditor>
  )
}
