import { useState } from 'react'
import { Lien2PrintLayer } from './Lien2Label'
import { reloadAfterPrint, usePrintQueue } from '../lib/printQueue'

// Nút "In liên 2" + modal in CHỦ ĐỘNG (Stage 6.9, queue 6.9.4) — tái dùng ở mọi nơi
// có nút in bill. Chọn số nhãn (nhanh 1–5 / stepper) + tuỳ chọn đánh số. MỖI NHÃN
// = 1 window.print() RIÊNG (queue tuần tự) → máy Sunmi cắt rời từng tờ, đúng thứ tự
// 1/N → N/N. KHÔNG phụ thuộc auto_print_receipt.
const MAX = 20
const clamp = (n) => Math.max(1, Math.min(MAX, n))

export default function Lien2PrintButton({ order, className = 'btn btn--ghost' }) {
  const [open, setOpen] = useState(false)
  const [count, setCount] = useState(1)
  const [numbered, setNumbered] = useState(true)
  const { active, printing, run } = usePrintQueue()

  const openModal = () => {
    setCount(1)
    setNumbered(true)
    setOpen(true)
  }

  const doPrint = () => {
    if (printing) return
    // ⭐ Part C (fix T2): 1 JOB DUY NHẤT gộp N nhãn (KHÔNG còn N job × N print → print lần 2+
    // crash). Lien2PrintLayer render N khối .lbl trong 1 .print-lien2 → printViaIframe in 1
    // print. Xong → reloadAfterPrint (full reload → document kế "print lần 1", không crash).
    run([{ mode: 'lien2', count, numbered }], () => reloadAfterPrint(700))
  }

  if (!order) return null

  return (
    <>
      <button type="button" className={className} onClick={openModal}>In liên 2</button>

      {open && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <div className="modal lien2m">
            <div className="lien2m__head">
              <span className="lien2m__title">In liên 2 · {order.order_code}</span>
              <button type="button" className="lien2m__x" onClick={() => setOpen(false)} disabled={printing} aria-label="Đóng">×</button>
            </div>
            <div className="lien2m__body">
              <div className="lien2m__lbl">Số nhãn</div>
              <div className="lien2m__quick">
                {[1, 2, 3, 4, 5].map((n) => (
                  <button type="button" key={n}
                    className={`lien2m__q ${count === n ? 'lien2m__q--on' : ''}`}
                    onClick={() => setCount(n)} disabled={printing}>{n}</button>
                ))}
              </div>
              <div className="lien2m__manual">
                <span>Hoặc nhập:</span>
                <div className="stepper">
                  <button type="button" onClick={() => setCount((c) => clamp(c - 1))} disabled={printing}>−</button>
                  <span className="stepper__val">{count}</span>
                  <button type="button" onClick={() => setCount((c) => clamp(c + 1))} disabled={printing}>+</button>
                </div>
              </div>
              <label className="lien2m__chk">
                <input type="checkbox" checked={numbered} onChange={(e) => setNumbered(e.target.checked)} disabled={printing} />
                <span>Đánh số (1/{count}, 2/{count}…)</span>
              </label>
            </div>
            <div className="lien2m__foot">
              <button type="button" className="btn btn--ghost lien2m__cancel" onClick={() => setOpen(false)} disabled={printing}>
                Huỷ
              </button>
              <button type="button" className="btn btn--primary lien2m__print" onClick={doPrint} disabled={printing}>
                {printing ? 'Đang in…' : `In ${count} nhãn`}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* Render N nhãn GỘP (1 job) vào vùng in khi đang in. */}
      {active?.mode === 'lien2' && <Lien2PrintLayer order={order} count={active.count} numbered={active.numbered} />}
    </>
  )
}
