import { useState } from 'react'
import Ico from './Ico'
import { ADDABLE, blockListLabel, removeCellFromRows } from '../../lib/receipt'

// Trình sửa DANH SÁCH khối (list + thêm + sắp xếp/ghép/tách + kéo-thả) — DÙNG LẠI
// cho cả khối CHUNG lẫn từng CN (khu "Liên hệ theo chi nhánh"). Mỗi instance giữ
// dragRi riêng (kéo-thả không lẫn giữa 2 khu). Sửa nội dung 1 khối → gọi
// onOpenEdit(scopeKey, ri, ci) lên cha (modal dùng chung). mutate(fn): cha truyền
// hàm áp đổi vào ĐÚNG mảng theo scope (đã đánh dấu dirty + slice sẵn).
// (Stage refactor editor: MOVE nguyên từ ReceiptSettings — KHÔNG đổi logic.)
export default function BlockListEditor({ rows, mutate, canEdit, scopeKey, onOpenEdit }) {
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
