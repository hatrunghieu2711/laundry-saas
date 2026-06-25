import { useCallback, useEffect, useState } from 'react'
import { api } from '../../lib/api'
import {
  ADDABLE,
  blockListLabel,
  blocksToRows,
  removeCellFromRows,
  rowsToBlocks,
} from '../../lib/receipt'

// Editor mẫu in CHUẨN system-wide (Super Admin). Tái dùng blocksToRows/rowsToBlocks (shared).
// Sửa phần CHUNG: blocks (thêm/sửa/xóa/thứ tự) + bilingual + track_base_url.
// KHÔNG: logo upload / auto_print / branch_contact / iframe (đều per-tenant).
export default function AdminDefaultReceipt() {
  const [bilingual, setBilingual] = useState(true)
  const [trackBase, setTrackBase] = useState('')
  const [rows, setRows] = useState(null) // mảng hàng, mỗi hàng 1-2 khối
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [edit, setEdit] = useState(null) // {ri, ci} khối custom_text đang sửa
  const [editC, setEditC] = useState({}) // {vi, en}

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const c = await api.admin.getDefaultReceipt()
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

  const moveRow = (ri, dir) => {
    setRows((rs) => {
      const j = ri + dir
      if (j < 0 || j >= rs.length) return rs
      const next = rs.slice()
      ;[next[ri], next[j]] = [next[j], next[ri]]
      return next
    })
    dirty()
  }

  const toggle = (ri, ci) => {
    setRows((rs) => rs.map((row, i) => (i === ri
      ? row.map((b, c) => (c === ci ? { ...b, enabled: !(b.enabled !== false) } : b))
      : row)))
    dirty()
  }

  const removeCell = (ri, ci) => {
    setRows((rs) => removeCellFromRows(rs, ri, ci))
    dirty()
  }

  const addBlock = (type) => {
    const blk = { id: `${type}_${Date.now()}`, type, enabled: true, row: 0, col: 'full', removable: true, content: {} }
    setRows((rs) => [...rs, [blk]])
    dirty()
  }

  const openEdit = (ri, ci) => {
    setEdit({ ri, ci })
    setEditC({ ...(rows[ri][ci].content || {}) })
  }

  const saveEdit = () => {
    const { ri, ci } = edit
    setRows((rs) => rs.map((row, i) => (i === ri
      ? row.map((b, c) => (c === ci ? { ...b, content: { ...editC } } : b))
      : row)))
    setEdit(null)
    dirty()
  }

  const save = async () => {
    setSaving(true)
    setError('')
    try {
      const blocks = rowsToBlocks(rows)
      await api.admin.setDefaultReceipt({ bilingual, track_base_url: trackBase.trim(), blocks })
      setSaved(true)
    } catch (e) {
      setError(e?.message || 'Không lưu được mẫu in')
    } finally {
      setSaving(false)
    }
  }

  if (loading) return <p className="shift__hint">Đang tải…</p>
  if (rows === null) return <div className="alert alert--error">{error || 'Lỗi'}</div>

  return (
    <div className="services">
      <div className="services__head">
        <h2 className="services__title">Mẫu in mặc định</h2>
        <button className="btn btn--primary btn--sm" onClick={save} disabled={saving}>
          {saving ? 'Đang lưu…' : 'Lưu mẫu'}
        </button>
      </div>
      <p className="shift__hint" style={{ marginTop: -4 }}>
        Mẫu chuẩn áp cho <strong>cửa hàng tạo MỚI</strong> (copy vào cấu hình của họ). Cửa hàng đang
        có KHÔNG đổi. Logo, liên hệ chi nhánh, tự động in… do từng cửa hàng tự đặt.
      </p>

      {error && <div className="alert alert--error">{error}</div>}
      {saved && <div className="alert alert--success">Đã lưu mẫu chuẩn.</div>}

      {/* Tùy chọn chung */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Tùy chọn chung</div>
        <label className="field" style={{ flexDirection: 'row', alignItems: 'center', gap: 8 }}>
          <input type="checkbox" checked={bilingual} onChange={(e) => { setBilingual(e.target.checked); dirty() }} />
          <span>Song ngữ (hiện tiếng Anh)</span>
        </label>
        <label className="field">
          <span>Link tra cứu (track_base_url) — để trống dùng mặc định</span>
          <input className="input" type="text" value={trackBase} autoCapitalize="none"
            placeholder="https://track.giatui.app/track/{slug}/"
            onChange={(e) => { setTrackBase(e.target.value); dirty() }} />
        </label>
      </div>

      {/* Khối bill */}
      <div className="card" style={{ marginTop: 12 }}>
        <div className="card__title">Các khối trên phiếu</div>
        <div className="cat-group">
          {rows.map((row, ri) => (
            <div className="cat-item" key={ri}>
              <div className="cat-item__main">
                {row.map((b, ci) => (
                  <div key={ci} style={{ display: 'flex', alignItems: 'center', gap: 8, padding: '2px 0' }}>
                    <input type="checkbox" checked={b.enabled !== false} onChange={() => toggle(ri, ci)} title="Bật/tắt" />
                    <span style={{ flex: 1, opacity: b.enabled !== false ? 1 : 0.5 }}>{blockListLabel(b)}</span>
                    {b.type === 'custom_text' && (
                      <button className="btn btn--ghost btn--sm" onClick={() => openEdit(ri, ci)}>Sửa</button>
                    )}
                    {b.removable && (
                      <button className="btn btn--ghost btn--sm" onClick={() => removeCell(ri, ci)} title="Xóa khối">✕</button>
                    )}
                  </div>
                ))}
              </div>
              <div style={{ display: 'flex', flexDirection: 'column', gap: 2 }}>
                <button className="btn btn--ghost btn--sm" onClick={() => moveRow(ri, -1)} disabled={ri === 0} title="Lên">↑</button>
                <button className="btn btn--ghost btn--sm" onClick={() => moveRow(ri, 1)} disabled={ri === rows.length - 1} title="Xuống">↓</button>
              </div>
            </div>
          ))}
        </div>
        <div style={{ display: 'flex', flexWrap: 'wrap', gap: 8, marginTop: 10 }}>
          {ADDABLE.map((a) => (
            <button key={a.type} className="btn btn--ghost btn--sm" onClick={() => addBlock(a.type)}>{a.label}</button>
          ))}
        </div>
      </div>

      {/* Modal sửa văn bản tự do */}
      {edit && (
        <div className="modal-overlay modal-overlay--top" role="dialog" aria-modal="true" onClick={() => setEdit(null)}>
          <div className="panel panel--modal" onClick={(e) => e.stopPropagation()}>
            <div className="panel__head"><span className="panel__title">Sửa văn bản</span></div>
            <div className="panel__body">
              <div className="panel__group">
                <label className="field">
                  <span>Nội dung (VI)</span>
                  <textarea className="input" rows={3} value={editC.vi || ''} onChange={(e) => setEditC((c) => ({ ...c, vi: e.target.value }))} />
                </label>
                <label className="field">
                  <span>Nội dung (EN)</span>
                  <textarea className="input" rows={3} value={editC.en || ''} onChange={(e) => setEditC((c) => ({ ...c, en: e.target.value }))} />
                </label>
              </div>
            </div>
            <div className="panel__foot">
              <button className="btn btn--ghost" onClick={() => setEdit(null)}>Hủy</button>
              <button className="btn btn--primary" onClick={saveEdit}>Xong</button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
