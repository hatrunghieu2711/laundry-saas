import { useState } from 'react'
import {
  BLOCK_LABELS,
  BLOCK_META,
  BLOCK_VALUES,
  canItalic,
  defaultAlign,
  isField,
} from '../../lib/receipt'

// Modal sửa 1 khối (nhãn · nội dung · định dạng đậm/nghiêng/căn lề/cỡ chữ/title · divider
// style · spacer height · logo). TỰ CHỨA state editContent/editFmt khởi tạo TỪ block prop
// (port nguyên openEdit/saveEdit của ReceiptSettings). "Xong" → onSave({content, ...fmt}); cha
// áp { ...block, ...kết-quả } vào mảng của mình (chung hoặc CN). onUploadLogo undefined → ẩn
// nút upload (admin mẫu chuẩn) NHƯNG vẫn sửa định dạng đầy đủ.
export default function BlockEditModal({
  block, bilingual, canEdit, logoUrl, onUploadLogo, uploading, fileRef, onSave, onClose,
}) {
  const type = block.type
  const [editContent, setEditContent] = useState(() => ({ ...(block.content || {}) }))
  const [editFmt, setEditFmt] = useState(() => ({
    bold: !!block.bold,
    bold_label: block.bold_label ?? !!block.bold,
    bold_value: block.bold_value ?? !!block.bold,
    italic: !!block.italic,
    title: !!block.title,
    align: block.align || defaultAlign(type),
    size: block.size || 'normal',
  }))
  const setC = (k, v) => setEditContent((c) => ({ ...c, [k]: v }))
  const setF = (k, v) => setEditFmt((f) => ({ ...f, [k]: v }))

  return (
    <div className="modal-overlay" role="dialog" aria-modal="true">
      <div className="modal modal--scroll">
        <h3 className="modal__title">Sửa: {BLOCK_META[type]?.label}</h3>

        {/* Logo: upload ảnh */}
        {type === 'logo' && (
          <div className="rcfg__logo">
            <div className="rcfg__logo-prev">
              {logoUrl ? <img src={logoUrl} alt="logo" /> : <span className="rcfg__logo-text">{editContent.logo_text || '—'}</span>}
            </div>
            {onUploadLogo && (
              <div className="rcfg__logo-actions">
                <input ref={fileRef} type="file" accept="image/png,image/jpeg" className="rcfg__file" disabled={!canEdit || uploading} onChange={onUploadLogo} />
                <p className="rcfg__hint">Ảnh PNG/JPG ≤500KB. Lưu ngay khi chọn.</p>
                {uploading && <p className="rcfg__hint">Đang tải logo…</p>}
              </div>
            )}
          </div>
        )}

        {/* Divider: kiểu kẻ */}
        {type === 'divider' && (
          <div className="fmt-row"><span>Kiểu kẻ</span>
            <div className="seg seg--sm">
              <button className={`seg__btn ${(editContent.style || 'dashed') === 'dashed' ? 'seg__btn--active' : ''}`} onClick={() => setC('style', 'dashed')}>- - -</button>
              <button className={`seg__btn ${editContent.style === 'solid' ? 'seg__btn--active' : ''}`} onClick={() => setC('style', 'solid')}>───</button>
            </div>
          </div>
        )}
        {/* Spacer: chiều cao */}
        {type === 'spacer' && (
          <div className="fmt-row"><span>Chiều cao</span>
            <div className="seg seg--sm">
              <button className={`seg__btn ${(editContent.height || 'small') === 'small' ? 'seg__btn--active' : ''}`} onClick={() => setC('height', 'small')}>Nhỏ</button>
              <button className={`seg__btn ${editContent.height === 'medium' ? 'seg__btn--active' : ''}`} onClick={() => setC('height', 'medium')}>Vừa</button>
            </div>
          </div>
        )}

        {/* Giá trị text owner nhập (logo / văn bản tự do) */}
        {(BLOCK_VALUES[type] || []).filter((f) => !f.en || bilingual).map((f) => (
          <label className="field" key={f.key}>
            <span>{f.label}</span>
            {f.area
              ? <textarea className="input rcfg__ta" rows={3} value={editContent[f.key] || ''} onChange={(e) => setC(f.key, e.target.value)} />
              : <input className="input" value={editContent[f.key] || ''} onChange={(e) => setC(f.key, e.target.value)} />}
          </label>
        ))}

        {/* Nhãn hiển thị (song ngữ) */}
        {(BLOCK_LABELS[type] || []).length > 0 && (
          <div className="lbl-edit">
            <div className="lbl-edit__title">Nhãn hiển thị {bilingual ? '(Việt / Anh)' : '(Tiếng Việt)'}</div>
            {BLOCK_LABELS[type].map((l) => (
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
        {!['divider', 'spacer'].includes(type) && (
          <div className="fmt-controls">
            {type === 'custom_text' && (
              <label className="rcfg__switch"><input type="checkbox" checked={editFmt.title} onChange={(e) => setF('title', e.target.checked)} /><span>Tiêu đề (cỡ lớn nhất · đậm · căn giữa)</span></label>
            )}
            <div className="fmt-row fmt-row--bold">
              {isField(type) ? (
                <>
                  <label className="rcfg__switch"><input type="checkbox" checked={editFmt.bold_label} onChange={(e) => setF('bold_label', e.target.checked)} /><span>Đậm nhãn</span></label>
                  <label className="rcfg__switch"><input type="checkbox" checked={editFmt.bold_value} onChange={(e) => setF('bold_value', e.target.checked)} /><span>Đậm giá trị</span></label>
                </>
              ) : (
                <label className="rcfg__switch"><input type="checkbox" checked={editFmt.bold} onChange={(e) => setF('bold', e.target.checked)} /><span>In đậm</span></label>
              )}
              {canItalic(type) && (
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
          <button className="btn btn--ghost btn--lg" onClick={onClose}>Quay lại</button>
          <button className="btn btn--primary btn--lg" onClick={() => onSave({ content: { ...editContent }, ...editFmt })} disabled={!canEdit}>Xong</button>
        </div>
      </div>
    </div>
  )
}
