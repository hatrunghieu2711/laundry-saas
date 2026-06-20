import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import MoneyInput from '../components/MoneyInput'
import ShiftEmpty from '../components/ShiftEmpty'
import { useAuth } from '../context/AuthContext'
import { ApiError, api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'

// Danh mục gợi ý theo loại (vẫn cho gõ tự do).
const CATEGORIES = {
  income: ['Thu khác', 'Thu nợ khách', 'Bán phụ liệu'],
  expense: ['Mua vật tư', 'Tiền điện', 'Tiền nước', 'Ứng lương', 'Sửa máy', 'Chi khác'],
}
const METHODS = [
  ['cash', 'Tiền mặt'],
  ['transfer', 'Chuyển khoản'],
  ['qr', 'QR'],
]
const METHOD_LABEL = Object.fromEntries(METHODS)

// Gom tiền mặt đã thu qua payments của ca (để tính tồn quỹ thực tế trong két).
async function fetchCashPayments(shiftId) {
  let cash = 0
  const limit = 200
  let offset = 0
  for (;;) {
    const page = await api.get(`/payments?shift_id=${shiftId}&limit=${limit}&offset=${offset}`)
    for (const p of page.items) {
      if (p.payment_method === 'cash') cash += toNumber(p.amount)
    }
    offset += page.items.length
    if (page.items.length === 0 || offset >= page.total) break
  }
  return cash
}

async function fetchCashTransactions(shiftId) {
  const items = []
  const limit = 200
  let offset = 0
  for (;;) {
    const page = await api.get(`/cash-transactions?shift_id=${shiftId}&limit=${limit}&offset=${offset}`)
    items.push(...page.items)
    offset += page.items.length
    if (page.items.length === 0 || offset >= page.total) break
  }
  return items
}

export default function CashBook() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(isOwner ? null : user?.branch_id || null)
  const [shift, setShift] = useState(undefined) // undefined=loading, null=chưa có ca, obj
  const [items, setItems] = useState([])
  const [cashPaid, setCashPaid] = useState(0)
  const [error, setError] = useState('')

  // Form thêm thu/chi (null = đóng).
  const [form, setForm] = useState(null) // { type, amount, category, note, method }
  const [busy, setBusy] = useState(false)

  // Owner: nạp danh sách branch.
  useEffect(() => {
    if (!isOwner) return
    api
      .get('/branches?limit=200')
      .then((p) => {
        const active = p.items.filter((b) => b.status === 'active')
        setBranches(active)
        if (active.length === 1) setBranchId(active[0].id)
      })
      .catch(() => {})
  }, [isOwner])

  const load = useCallback(async () => {
    setError('')
    if (isOwner && !branchId) {
      setShift(undefined)
      return
    }
    setShift(undefined)
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      const s = await api.get(`/shifts/current${q}`)
      setShift(s)
      const [txs, cash] = await Promise.all([
        fetchCashTransactions(s.id),
        fetchCashPayments(s.id),
      ])
      setItems(txs)
      setCashPaid(cash)
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setShift(null)
      } else {
        setShift(null)
        setError(err?.message || 'Không tải được sổ quỹ')
      }
    }
  }, [isOwner, branchId])

  useEffect(() => {
    load()
  }, [load])

  // Tổng thu / chi (mọi phương thức) + phần tiền mặt (ảnh hưởng két).
  const totals = items.reduce(
    (acc, t) => {
      const amt = toNumber(t.amount)
      if (t.type === 'income') {
        acc.income += amt
        if (t.payment_method === 'cash') acc.incomeCash += amt
      } else {
        acc.expense += amt
        if (t.payment_method === 'cash') acc.expenseCash += amt
      }
      return acc
    },
    { income: 0, expense: 0, incomeCash: 0, expenseCash: 0 },
  )
  // Tồn quỹ tiền mặt = đầu ca + tiền mặt thu đơn + thu tiền mặt - chi tiền mặt.
  const cashOnHand =
    toNumber(shift?.opening_cash) + cashPaid + totals.incomeCash - totals.expenseCash

  const openForm = (type) =>
    setForm({ type, amount: '', category: '', note: '', method: 'cash' })

  const submit = async (e) => {
    e.preventDefault()
    if (busy) return
    setBusy(true)
    setError('')
    try {
      const body = {
        type: form.type,
        amount: toNumber(form.amount),
        category: form.category.trim(),
        payment_method: form.method,
      }
      if (form.note.trim()) body.note = form.note.trim()
      if (isOwner) body.branch_id = branchId
      await api.post('/cash-transactions', body)
      setForm(null)
      await load()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_OPEN_SHIFT') {
        setError('Cần mở ca trước khi ghi thu/chi.')
      } else if (err instanceof ApiError && err.code === 'INVALID_AMOUNT') {
        setError('Số tiền phải lớn hơn 0.')
      } else if (err instanceof ApiError && err.code === 'CATEGORY_REQUIRED') {
        setError('Vui lòng chọn hoặc nhập danh mục.')
      } else {
        setError(err?.message || 'Không ghi được giao dịch')
      }
    } finally {
      setBusy(false)
    }
  }

  // ── Owner: bộ chọn chi nhánh ───────────────────────────────────────
  const branchPicker = isOwner && (
    <div className="branch-picker">
      <span className="branch-picker__label">Chi nhánh</span>
      <div className="branch-picker__chips">
        {branches.map((b) => (
          <button
            key={b.id}
            className={`chip ${branchId === b.id ? 'chip--active' : ''}`}
            onClick={() => setBranchId(b.id)}
          >
            {b.code} · {b.name}
          </button>
        ))}
      </div>
    </div>
  )

  return (
    <div className="cashbook">
      {branchPicker}
      {error && <div className="alert alert--error">{error}</div>}

      {isOwner && !branchId && <p className="shift__hint">Chọn một chi nhánh để xem sổ quỹ.</p>}

      {shift === undefined && branchId && <p className="shift__hint">Đang tải sổ quỹ…</p>}

      {shift === null && (!isOwner || branchId) && (
        <ShiftEmpty>
          <p>Chưa có ca nào đang mở.</p>
          <button className="btn btn--primary btn--xl btn--block" onClick={() => navigate('/')}>
            Về màn ca để mở ca
          </button>
        </ShiftEmpty>
      )}

      {shift && (
        <>
          {/* Tổng quan */}
          <div className="card cashbook__totals">
            <div className="summary">
              <div className="summary__row">
                <span>＋ Tổng thu</span>
                <strong className="cashbook__in">{formatVND(totals.income)}</strong>
              </div>
              <div className="summary__row">
                <span>－ Tổng chi</span>
                <strong className="cashbook__out">{formatVND(totals.expense)}</strong>
              </div>
              <div className="summary__row summary__row--head">
                <span>Tồn quỹ tiền mặt</span>
                <strong>{formatVND(cashOnHand)}</strong>
              </div>
            </div>
            <p className="cashbook__hint">
              Tồn quỹ = đầu ca {formatVND(shift.opening_cash)} + tiền mặt thu đơn + thu − chi tiền mặt.
            </p>
          </div>

          {/* Nút nhập nhanh */}
          <div className="cashbook__actions">
            <button className="btn btn--success btn--xl" onClick={() => openForm('income')}>
              ＋ Thu
            </button>
            <button className="btn btn--danger btn--xl" onClick={() => openForm('expense')}>
              － Chi
            </button>
          </div>

          {/* Danh sách giao dịch */}
          {items.length === 0 ? (
            <p className="shift__hint">Chưa có khoản thu/chi nào trong ca này.</p>
          ) : (
            <ul className="cashbook__list">
              {items.map((t) => (
                <li key={t.id} className={`cashbook__item cashbook__item--${t.type}`}>
                  <div className="cashbook__item-main">
                    <span className="cashbook__item-cat">{t.category}</span>
                    {t.note && <span className="cashbook__item-note">{t.note}</span>}
                    <span className="cashbook__item-meta">
                      {METHOD_LABEL[t.payment_method] || t.payment_method}
                      {' · '}
                      {t.created_by_name || '—'}
                      {' · '}
                      {formatDateTime(t.created_at)}
                    </span>
                  </div>
                  <strong className={t.type === 'income' ? 'cashbook__in' : 'cashbook__out'}>
                    {t.type === 'income' ? '+' : '−'}
                    {formatVND(t.amount)}
                  </strong>
                </li>
              ))}
            </ul>
          )}
        </>
      )}

      {/* Modal nhập thu/chi */}
      {form && (
        <div className="modal-overlay" role="dialog" aria-modal="true">
          <form className="modal modal--confirm" onSubmit={submit}>
            <h3 className="modal__title">
              {form.type === 'income' ? '＋ Ghi khoản thu' : '－ Ghi khoản chi'}
            </h3>
            {error && <div className="alert alert--error">{error}</div>}

            <label className="field">
              <span>Số tiền</span>
              <MoneyInput
                value={form.amount}
                onChange={(v) => setForm((f) => ({ ...f, amount: v }))}
                autoFocus
                required
              />
            </label>

            <span className="field-label">Danh mục</span>
            <div className="chip-row">
              {CATEGORIES[form.type].map((c) => (
                <button
                  type="button"
                  key={c}
                  className={`chip chip--sm ${form.category === c ? 'chip--active' : ''}`}
                  onClick={() => setForm((f) => ({ ...f, category: c }))}
                >
                  {c}
                </button>
              ))}
            </div>
            <input
              className="input"
              type="text"
              placeholder="Hoặc nhập danh mục khác…"
              value={form.category}
              onChange={(e) => setForm((f) => ({ ...f, category: e.target.value }))}
            />

            <span className="field-label" style={{ marginTop: 12 }}>
              Phương thức
            </span>
            <div className="method-grid">
              {METHODS.map(([k, label]) => (
                <button
                  type="button"
                  key={k}
                  className={`method-btn ${form.method === k ? 'method-btn--active' : ''}`}
                  onClick={() => setForm((f) => ({ ...f, method: k }))}
                >
                  {label}
                </button>
              ))}
            </div>

            <label className="field" style={{ marginTop: 12 }}>
              <span>Ghi chú (tùy chọn)</span>
              <input
                className="input"
                type="text"
                value={form.note}
                onChange={(e) => setForm((f) => ({ ...f, note: e.target.value }))}
              />
            </label>

            <div className="modal__actions modal__actions--row">
              <button
                type="button"
                className="btn btn--ghost btn--lg"
                onClick={() => {
                  setForm(null)
                  setError('')
                }}
              >
                Hủy
              </button>
              <button
                type="submit"
                className={`btn btn--xl ${form.type === 'income' ? 'btn--success' : 'btn--danger'}`}
                disabled={busy || toNumber(form.amount) <= 0 || !form.category.trim()}
              >
                {busy ? 'Đang ghi…' : 'Lưu'}
              </button>
            </div>
          </form>
        </div>
      )}
    </div>
  )
}
