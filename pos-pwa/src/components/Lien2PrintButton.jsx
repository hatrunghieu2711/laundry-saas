import { useEffect, useRef, useState } from 'react'
import { createPortal } from 'react-dom'
import { Lien2LabelBody } from './Lien2Label'

// Nút "In liên 2" + modal in CHỦ ĐỘNG (Stage 6.9) — tái dùng ở mọi nơi có nút in
// bill. Chọn số nhãn (nhanh 1–5 / stepper) + tuỳ chọn đánh số. In RỜI từng nhãn
// (page-break giữa các nhãn → máy tự cắt). KHÔNG phụ thuộc auto_print_receipt.
//
// CẦN TEST TRÊN SUNMI: in liên tiếp nhiều nhãn + tự cắt giữa các nhãn; và sự kiện
// 'afterprint' (nếu máy không bắn → nhân viên bấm "Đóng" để dọn).
const MAX = 20
const clamp = (n) => Math.max(1, Math.min(MAX, n))

export default function Lien2PrintButton({ order, className = 'btn btn--ghost' }) {
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState(1)
  const [numbered, setNumbered] = useState(true)
  const [printing, setPrinting] = useState(false)
  const afterRef = useRef(null)

  const cleanup = () => {
    document.body.classList.remove('print-mode-lien2')
    if (afterRef.current) {
      window.removeEventListener('afterprint', afterRef.current)
      afterRef.current = null
    }
    setPrinting(false)
  }
  useEffect(() => () => cleanup(), []) // dọn khi unmount

  const close = () => {
    cleanup()
    setOpen(false)
  }
  const openModal = () => {
    setCount(1)
    setNumbered(true)
    setOpen(true)
  }

  const doPrint = () => {
    if (printing) return
    setPrinting(true) // render portal nhãn
    document.body.classList.add('print-mode-lien2') // CSS: ẩn bill, hiện .print-lien2
    requestAnimationFrame(() => {
      const after = () => close() // in xong → dọn + đóng modal
      afterRef.current = after
      window.addEventListener('afterprint', after)
      window.print()
      // KHÔNG tự dọn bằng timeout (tránh gỡ nhãn trước khi máy in xong — in async).
    })
  }

  if (!order) return null
  const labels = Array.from({ length: count }, (_, i) => (numbered ? { n: i + 1, total: count } : null))

  return (
    <>
      <button type="button" className={className} onClick={openModal}>In liên 2</button>

      {open && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal lien2m">
            <div className="lien2m__head">
              <span className="lien2m__title">In liên 2 · {order.order_code}</span>
              <button type="button" className="lien2m__x" onClick={close} aria-label="Đóng">×</button>
            </div>
            <div className="lien2m__body">
              <div className="lien2m__lbl">Số nhãn</div>
              <div className="lien2m__quick">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button type="button" key={n}
                    className={`lien2m__q ${count === n ? 'lien2m__q--on' : ''}`}
                    onClick={() => setCount(n)}>{n}</button>
                ))}
              </div>
              <div className="lien2m__manual">
                <span>Hoặc nhập:</span>
                <div className="stepper">
                  <button type="button" onClick={() => setCount((c) => clamp(c - 1))}>−</button>
                  <span className="stepper__val">{count}</span>
                  <button type="button" onClick={() => setCount((c) => clamp(c + 1))}>+</button>
                </div>
              </div>
              <label className="lien2m__chk">
                <input type="checkbox" checked={numbered} onChange={(e) => setNumbered(e.target.checked)} />
                <span>Đánh số (1/{count}, 2/{count}…)</span>
              </label>
            </div>
            <div className="lien2m__foot">
              <button type="button" className="btn btn--ghost lien2m__cancel" onClick={close}>
                {printing ? 'Đóng' : 'Huỷ'}
              </button>
              <button type="button" className="btn btn--primary lien2m__print" onClick={doPrint} disabled={printing}>
                {printing ? 'Đang in…' : `In ${count} nhãn`}
              </button>
            </div>
          </div>
        </div>
      )}

      {printing && createPortal(
        <div className="print-lien2">
          {labels.map((seq, i) => (
            <div className="lbl-page" key={i}><Lien2LabelBody order={order} seq={seq} /></div>
          ))}
        </div>,
        document.body,
      )}
    </>
  )
}
