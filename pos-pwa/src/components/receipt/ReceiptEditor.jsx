import BlockListEditor from './BlockListEditor'
import BlockEditModal from './BlockEditModal'
import ReceiptPreview from './ReceiptPreview'

// Editor mẫu in DÙNG CHUNG (tenant ReceiptSettings + admin mẫu chuẩn — Bước 2). Bao layout
// rcfg 2 cột: cột trái = options (bilingual + track + optionsExtra) + khối CHUNG + children
// (tenant chèn branch_contact/save/default); cột phải = preview. CONTROLLED: state rows/
// bilingual/track + gates do CHA giữ (payload bất biến). `editing` ({ri,ci}|null) controlled →
// modal khối CHUNG; cha biết modal nào mở (ẩn alert đúng lúc).
export default function ReceiptEditor({
  title, canEdit, readOnlyHint,
  bilingual, onBilingual, trackBaseUrl, onTrackBaseUrl,
  rows, mutateRows, editing, onEditing,
  logoUrl, onUploadLogo, uploading, fileRef,
  slug, preview, optionsExtra, children,
}) {
  return (
    <div className="rcfg">
      <div className="rcfg__editor">
        <h2 className="services__title">{title}</h2>
        {!canEdit && readOnlyHint && <div className="alert alert--error">{readOnlyHint}</div>}

        <div className="shift__card">
          <div className="rcfg__card-head">
            <h3 className="card__title">Tùy chọn chung</h3>
            <label className="rcfg__switch">
              <input type="checkbox" checked={bilingual} disabled={!canEdit} onChange={(e) => onBilingual(e.target.checked)} />
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
              placeholder="https://tenmiencuaban.com/track/?code="
              onChange={(e) => onTrackBaseUrl(e.target.value)} />
          </label>
          <p className="rcfg__hint">
            Để trống = mặc định track.giatui.app. Có web riêng để tra cứu: đặt link track của bạn
            KẾT THÚC bằng “?code=” (QR = link này + mã đơn).
          </p>
          {optionsExtra}
        </div>

        <div className="shift__card">
          <h3 className="card__title">Các khối trên phiếu</h3>
          <BlockListEditor rows={rows} mutate={mutateRows} canEdit={canEdit} scopeKey={null}
            onOpenEdit={(_, ri, ci) => onEditing({ ri, ci })} />
        </div>

        {children}
      </div>

      <ReceiptPreview {...preview} slug={slug} />

      {editing && (
        <BlockEditModal
          key={`${editing.ri}-${editing.ci}`}
          block={rows[editing.ri][editing.ci]}
          bilingual={bilingual}
          canEdit={canEdit}
          logoUrl={logoUrl}
          onUploadLogo={onUploadLogo}
          uploading={uploading}
          fileRef={fileRef}
          onSave={(f) => {
            mutateRows((rs) => { rs[editing.ri][editing.ci] = { ...rs[editing.ri][editing.ci], ...f }; return rs })
            onEditing(null)
          }}
          onClose={() => onEditing(null)}
        />
      )}
    </div>
  )
}
