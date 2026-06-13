import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import MoneyInput from '../components/MoneyInput'
import { useAuth } from '../context/AuthContext'
import { ApiError, api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'

// Ngưỡng lệch két để tô màu. Khớp default backend (tenant_settings.cash_diff_threshold).
// TODO: lấy từ API tenant settings khi có endpoint.
const CASH_DIFF_THRESHOLD = 50000

const METHODS = [
  ['cash', 'Tiền mặt'],
  ['transfer', 'Chuyển khoản'],
  ['qr', 'QR'],
  ['cod', 'COD'],
]

// Gom mọi payment của ca để tính tổng theo method + số đơn (ca đang mở chưa có
// aggregate ở backend — tính client-side, đúng công thức lúc đóng ca).
async function fetchShiftSummary(shiftId) {
  const totals = { cash: 0, transfer: 0, qr: 0, cod: 0 }
  const orderIds = new Set()
  const limit = 200
  let offset = 0
  for (;;) {
    const page = await api.get(`/payments?shift_id=${shiftId}&limit=${limit}&offset=${offset}`)
    for (const p of page.items) {
      if (totals[p.payment_method] !== undefined) totals[p.payment_method] += toNumber(p.amount)
      if (p.order_id) orderIds.add(p.order_id)
    }
    offset += page.items.length
    if (page.items.length === 0 || offset >= page.total) break
  }
  return { totals, ordersCount: orderIds.size }
}

function diffLevel(diff) {
  if (diff === 0) return 'ok'
  return Math.abs(diff) <= CASH_DIFF_THRESHOLD ? 'warn' : 'danger'
}

export default function Shift() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'

  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(isOwner ? null : user?.branch_id || null)
  const [shift, setShift] = useState(undefined) // undefined=loading, null=chưa có ca, obj=đang mở
  const [summary, setSummary] = useState(null)
  const [view, setView] = useState('main') // main | open | close | result
  const [opening, setOpening] = useState('')
  const [actual, setActual] = useState('')
  const [closed, setClosed] = useState(null)
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Owner: nạp danh sách branch để chọn.
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

  const loadCurrent = useCallback(async () => {
    setError('')
    setSummary(null)
    if (isOwner && !branchId) {
      setShift(undefined)
      return
    }
    setShift(undefined)
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      const s = await api.get(`/shifts/current${q}`)
      setShift(s)
      setSummary(await fetchShiftSummary(s.id))
    } catch (err) {
      if (err instanceof ApiError && err.status === 404) {
        setShift(null) // chưa có ca mở
      } else {
        setShift(null)
        setError(err?.message || 'Không tải được ca hiện tại')
      }
    }
  }, [isOwner, branchId])

  useEffect(() => {
    loadCurrent()
  }, [loadCurrent])

  const submitOpen = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const body = { opening_cash: toNumber(opening) }
      if (isOwner) body.branch_id = branchId
      await api.post('/shifts/open', body)
      setOpening('')
      setView('main')
      await loadCurrent()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'SHIFT_ALREADY_OPEN') {
        setError('Chi nhánh đang có ca mở.')
        await loadCurrent()
      } else {
        setError(err?.message || 'Không mở được ca, thử lại.')
      }
    } finally {
      setBusy(false)
    }
  }

  const submitClose = async (e) => {
    e.preventDefault()
    setBusy(true)
    setError('')
    try {
      const res = await api.post(`/shifts/${shift.id}/close`, {
        closing_cash_actual: toNumber(actual),
      })
      setClosed(res)
      setActual('')
      setView('result')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'SHIFT_CLOSED') {
        setError('Ca này đã được đóng.')
      } else {
        setError(err?.message || 'Không đóng được ca, thử lại.')
      }
    } finally {
      setBusy(false)
    }
  }

  const backToMain = async () => {
    setClosed(null)
    setView('main')
    await loadCurrent()
  }

  const expected = summary ? toNumber(shift?.opening_cash) + summary.totals.cash : 0
  const actualNum = toNumber(actual)
  const liveDiff = actualNum - expected
  const level = actual === '' ? null : diffLevel(liveDiff)

  // ── Owner: bộ chọn chi nhánh ───────────────────────────────────────
  const branchPicker = isOwner && (
    <div className="branch-picker">
      <span className="branch-picker__label">Chi nhánh</span>
      <div className="branch-picker__chips">
        {branches.map((b) => (
          <button
            key={b.id}
            className={`chip ${branchId === b.id ? 'chip--active' : ''}`}
            onClick={() => {
              setView('main')
              setBranchId(b.id)
            }}
          >
            {b.code} · {b.name}
          </button>
        ))}
      </div>
    </div>
  )

  return (
    <div className="shift">
      {branchPicker}
      {error && <div className="alert alert--error">{error}</div>}

      {isOwner && !branchId && (
        <p className="shift__hint">Chọn một chi nhánh để xem ca.</p>
      )}

      {/* ── KẾT QUẢ ĐÓNG CA ── */}
      {view === 'result' && closed && (
        <ResultCard closed={closed} onBack={backToMain} />
      )}

      {/* ── ĐANG TẢI ── */}
      {view === 'main' && shift === undefined && branchId && (
        <p className="shift__hint">Đang tải ca…</p>
      )}

      {/* ── CHƯA CÓ CA → MỞ CA ── */}
      {view === 'main' && shift === null && (!isOwner || branchId) && (
        <div className="shift__empty">
          <div className="shift__empty-icon">🕒</div>
          <p>Chưa có ca nào đang mở.</p>
          <button className="btn btn--primary btn--xl btn--block" onClick={() => setView('open')}>
            MỞ CA
          </button>
        </div>
      )}

      {/* ── FORM MỞ CA ── */}
      {view === 'open' && (
        <form className="card" onSubmit={submitOpen}>
          <h2 className="card__title">Mở ca</h2>
          <label className="field">
            <span>Tiền mặt đầu ca trong két</span>
            <MoneyInput value={opening} onChange={setOpening} autoFocus required />
          </label>
          <div className="row-actions">
            <button type="button" className="btn btn--ghost" onClick={() => setView('main')}>
              Hủy
            </button>
            <button type="submit" className="btn btn--primary btn--lg" disabled={busy || opening === ''}>
              {busy ? 'Đang mở…' : 'Xác nhận mở ca'}
            </button>
          </div>
        </form>
      )}

      {/* ── CA ĐANG MỞ ── */}
      {view === 'main' && shift && (
        <div className="card">
          <div className="badge badge--open">● Ca đang mở</div>
          <dl className="kv">
            <div><dt>Giờ mở</dt><dd>{formatDateTime(shift.opened_at)}</dd></div>
            <div>
              <dt>Người mở</dt>
              <dd>
                {shift.opened_by_name || '—'}
                {shift.opened_by === user?.id ? ' (bạn)' : ''}
              </dd>
            </div>
            <div><dt>Tiền đầu ca</dt><dd>{formatVND(shift.opening_cash)}</dd></div>
            <div><dt>Số đơn đã thu</dt><dd>{summary ? summary.ordersCount : '…'}</dd></div>
          </dl>
          <button
            className="btn btn--primary btn--xl btn--block"
            onClick={() => navigate('/orders/new')}
          >
            ＋ TẠO ĐƠN
          </button>
          <button
            className="btn btn--ghost btn--lg btn--block"
            style={{ marginTop: 10 }}
            onClick={() => setView('close')}
          >
            ĐÓNG CA
          </button>
        </div>
      )}

      {/* ── FORM ĐÓNG CA ── */}
      {view === 'close' && shift && (
        <form className="card" onSubmit={submitClose}>
          <h2 className="card__title">Đóng ca</h2>

          <div className="summary">
            <div className="summary__row summary__row--head">
              <span>Đã thu trong ca</span>
              <span>{summary ? `${summary.ordersCount} đơn` : '…'}</span>
            </div>
            {METHODS.map(([k, label]) => (
              <div className="summary__row" key={k}>
                <span>{label}</span>
                <span>{summary ? formatVND(summary.totals[k]) : '…'}</span>
              </div>
            ))}
          </div>

          <label className="field">
            <span>Tiền mặt thực đếm trong két</span>
            <MoneyInput value={actual} onChange={setActual} autoFocus required />
          </label>

          {/* So sánh dự kiến vs thực đếm — hiện NGAY khi gõ */}
          <div className={`diff diff--${level || 'idle'}`}>
            <div className="diff__line">
              <span>Dự kiến (đầu ca + tiền mặt)</span>
              <strong>{formatVND(expected)}</strong>
            </div>
            <div className="diff__line">
              <span>Thực đếm</span>
              <strong>{actual === '' ? '—' : formatVND(actualNum)}</strong>
            </div>
            <div className="diff__line diff__line--total">
              <span>Chênh lệch</span>
              <strong>
                {actual === ''
                  ? '—'
                  : `${liveDiff > 0 ? '+' : ''}${formatVND(liveDiff)}`}
              </strong>
            </div>
            {level === 'ok' && <p className="diff__note">Khớp két 👍</p>}
            {level === 'warn' && <p className="diff__note">Lệch nhỏ — kiểm tra lại tiền.</p>}
            {level === 'danger' && (
              <p className="diff__note">⚠️ Lệch lớn! Đếm lại trước khi xác nhận.</p>
            )}
          </div>

          <div className="row-actions">
            <button type="button" className="btn btn--ghost" onClick={() => setView('main')}>
              Quay lại
            </button>
            <button type="submit" className="btn btn--primary btn--lg" disabled={busy || actual === ''}>
              {busy ? 'Đang đóng…' : 'Xác nhận đóng ca'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

// Màn kết quả sau khi đóng ca.
function ResultCard({ closed, onBack }) {
  const diff = toNumber(closed.cash_difference)
  const level = diffLevel(diff)
  return (
    <div className="card">
      <h2 className="card__title">Đã đóng ca ✅</h2>
      <div className="summary">
        <div className="summary__row summary__row--head">
          <span>Số đơn</span>
          <span>{closed.orders_count ?? 0}</span>
        </div>
        {METHODS.map(([k, label]) => (
          <div className="summary__row" key={k}>
            <span>{label}</span>
            <span>{formatVND(closed[`total_${k}`])}</span>
          </div>
        ))}
      </div>
      <div className={`diff diff--${level}`}>
        <div className="diff__line">
          <span>Dự kiến</span>
          <strong>{formatVND(closed.closing_cash_expected)}</strong>
        </div>
        <div className="diff__line">
          <span>Thực đếm</span>
          <strong>{formatVND(closed.closing_cash_actual)}</strong>
        </div>
        <div className="diff__line diff__line--total">
          <span>Chênh lệch</span>
          <strong>{`${diff > 0 ? '+' : ''}${formatVND(diff)}`}</strong>
        </div>
      </div>
      <button className="btn btn--primary btn--xl btn--block" onClick={onBack}>
        Về trang ca
      </button>
    </div>
  )
}
