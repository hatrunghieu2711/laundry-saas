import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import MoneyInput from '../components/MoneyInput'
import ShiftSlip from '../components/ShiftSlip'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
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
  // Sổ quỹ thu-chi TIỀN MẶT (Stage 4.2) — vào/ra két, cộng vào dự kiến cuối ca.
  let incomeCash = 0
  let expenseCash = 0
  offset = 0
  for (;;) {
    const page = await api.get(`/cash-transactions?shift_id=${shiftId}&limit=${limit}&offset=${offset}`)
    for (const t of page.items) {
      if (t.payment_method !== 'cash') continue
      if (t.type === 'income') incomeCash += toNumber(t.amount)
      else expenseCash += toNumber(t.amount)
    }
    offset += page.items.length
    if (page.items.length === 0 || offset >= page.total) break
  }
  return { totals, ordersCount: orderIds.size, incomeCash, expenseCash }
}

function diffLevel(diff) {
  if (diff === 0) return 'ok'
  return Math.abs(diff) <= CASH_DIFF_THRESHOLD ? 'warn' : 'danger'
}

export default function Shift() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'

  // Bộ chọn chi nhánh DÙNG CHUNG trên thanh trên cùng (Stage 6.10).
  const { branchId, branches } = useBranch()
  const [shift, setShift] = useState(undefined) // undefined=loading, null=chưa có ca, obj=đang mở
  const [summary, setSummary] = useState(null) // client-side (cho form đóng ca)
  const [metrics, setMetrics] = useState(null) // realtime từ GET /shifts/{id}/summary (Stage 6.1)
  const [refreshing, setRefreshing] = useState(false)
  const [view, setView] = useState('main') // main | open | close | result
  const [opening, setOpening] = useState('')
  const [openSuggestion, setOpenSuggestion] = useState(0) // gợi ý đầu ca (Stage 6.2)
  const [actual, setActual] = useState('')
  const [handover, setHandover] = useState('') // rút nộp chủ (Stage 6.2)
  const [closed, setClosed] = useState(null)
  const [handoverBoard, setHandoverBoard] = useState(null) // tình hình bàn giao cho phiếu
  const [printSlip, setPrintSlip] = useState(null) // 'handover' | 'report'
  const [error, setError] = useState('')
  const [busy, setBusy] = useState(false)

  // Đổi chi nhánh (bộ chọn dùng chung trên thanh) → quay về màn chính.
  useEffect(() => {
    setView('main')
  }, [branchId])

  const loadCurrent = useCallback(async () => {
    setError('')
    setSummary(null)
    setMetrics(null)
    if (isOwner && !branchId) {
      setShift(undefined)
      return
    }
    setShift(undefined)
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      const s = await api.get(`/shifts/current${q}`)
      setShift(s)
      const [cs, m] = await Promise.all([
        fetchShiftSummary(s.id),
        api.get(`/shifts/${s.id}/summary`),
      ])
      setSummary(cs)
      setMetrics(m)
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

  // Mở form mở ca: lấy gợi ý đầu ca = tiền để lại ca trước (đếm lại rồi xác nhận).
  const startOpen = async () => {
    setError('')
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      const s = await api.get(`/shifts/opening-suggestion${q}`)
      const sug = toNumber(s.suggested_opening_cash)
      setOpenSuggestion(sug)
      setOpening(sug > 0 ? String(sug) : '')
    } catch {
      setOpenSuggestion(0)
    }
    setView('open')
  }

  // In phiếu: render slip vào portal rồi window.print().
  useEffect(() => {
    if (!printSlip) return undefined
    const t = setTimeout(() => {
      window.print()
      setPrintSlip(null)
    }, 150)
    return () => clearTimeout(t)
  }, [printSlip])

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
    const handoverNum = toNumber(handover)
    if (handoverNum > toNumber(actual)) {
      setError('Tiền nộp chủ không được vượt quá tiền thực đếm.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const res = await api.post(`/shifts/${shift.id}/close`, {
        closing_cash_actual: toNumber(actual),
        handover_to_owner: handoverNum,
      })
      // Tình hình bàn giao (cho biên bản): đơn đang xử lý / trễ hẹn / còn nợ.
      let board = null
      try {
        const q = isOwner ? `?branch_id=${branchId}` : ''
        const b = await api.get(`/orders/board${q}`)
        const cols = b.columns || {}
        const processing = ['created', 'washing', 'drying', 'ready']
          .reduce((s, k) => s + (cols[k]?.length || 0), 0)
        board = {
          processing,
          overdue: b.summary?.overdue || 0,
          owing: (b.summary?.unpaid || 0) + (b.summary?.debt || 0),
        }
      } catch {
        board = null
      }
      setHandoverBoard(board)
      setClosed(res)
      setActual('')
      setHandover('')
      setView('result')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'SHIFT_CLOSED') {
        setError('Ca này đã được đóng.')
      } else if (err instanceof ApiError && err.code === 'HANDOVER_EXCEEDS_CASH') {
        setError('Tiền nộp chủ không được vượt quá tiền thực đếm.')
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

  // Làm mới chỉ số realtime (không reset cả màn, tránh nháy).
  const refresh = async () => {
    if (!shift) return
    setRefreshing(true)
    try {
      const [cs, m] = await Promise.all([
        fetchShiftSummary(shift.id),
        api.get(`/shifts/${shift.id}/summary`),
      ])
      setSummary(cs)
      setMetrics(m)
    } catch (err) {
      setError(err?.message || 'Không làm mới được chỉ số')
    } finally {
      setRefreshing(false)
    }
  }

  const expected = summary
    ? toNumber(shift?.opening_cash) +
      summary.totals.cash +
      summary.incomeCash -
      summary.expenseCash
    : 0
  const actualNum = toNumber(actual)
  const liveDiff = actualNum - expected
  const level = actual === '' ? null : diffLevel(liveDiff)
  const handoverNum = toNumber(handover)
  const cashLeft = actualNum - handoverNum
  const handoverInvalid = handoverNum > actualNum
  const branchName = isOwner
    ? branches.find((b) => b.id === branchId)?.name || ''
    : user?.branch_name || ''

  return (
    <div className="shift">
      {error && <div className="alert alert--error">{error}</div>}

      {isOwner && !branchId && (
        <p className="shift__hint">Chọn một chi nhánh để xem ca.</p>
      )}

      {/* ── KẾT QUẢ ĐÓNG CA ── */}
      {view === 'result' && closed && (
        <ResultCard
          closed={closed}
          onBack={backToMain}
          onPrintHandover={() => setPrintSlip('handover')}
          onPrintReport={() => setPrintSlip('report')}
        />
      )}

      {/* Portal in phiếu giao ca (ẩn trên màn, hiện khi @media print). */}
      <ShiftSlip kind={printSlip} shift={closed} branchName={branchName} board={handoverBoard} />

      {/* ── ĐANG TẢI ── */}
      {view === 'main' && shift === undefined && branchId && (
        <p className="shift__hint">Đang tải ca…</p>
      )}

      {/* ── CHƯA CÓ CA → MỞ CA ── */}
      {view === 'main' && shift === null && (!isOwner || branchId) && (
        <div className="shift__empty">
          <div className="shift__empty-icon">🕒</div>
          <p>Chưa có ca nào đang mở.</p>
          <button className="btn btn--primary btn--xl btn--block" onClick={startOpen}>
            MỞ CA
          </button>
        </div>
      )}

      {/* ── FORM MỞ CA ── */}
      {view === 'open' && (
        <form className="card" onSubmit={submitOpen}>
          <h2 className="card__title">Mở ca</h2>
          {openSuggestion > 0 && (
            <p className="shift__hint">
              Gợi ý: ca trước để lại <strong>{formatVND(openSuggestion)}</strong> — đếm lại trong két rồi xác nhận/sửa.
            </p>
          )}
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
          <div className="shift__head">
            <div className="badge badge--open">● Ca đang mở</div>
            <button className="btn btn--ghost btn--sm" onClick={refresh} disabled={refreshing}>
              {refreshing ? '…' : '🔄 Làm mới'}
            </button>
          </div>
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
          </dl>

          {/* NHÓM Tiền trong ca (theo ca THU) */}
          <div className="metrics-group">
            <div className="metrics-group__title">Tiền trong ca</div>
            <div className="metric metric--hero">
              <span className="metric__label">💵 Tiền mặt trong két</span>
              <span className="metric__value">{metrics ? formatVND(metrics.cash_in_drawer) : '…'}</span>
            </div>
            <div className="metric">
              <span className="metric__label">🏦 Chuyển khoản / QR</span>
              <span className="metric__value">{metrics ? formatVND(metrics.transfer_total) : '…'}</span>
            </div>
            <div className="metric">
              <span className="metric__label">Tổng đã thu</span>
              <span className="metric__value">{metrics ? formatVND(metrics.total_collected) : '…'}</span>
            </div>
          </div>

          {/* NHÓM Doanh thu (theo ca TẠO đơn) */}
          <div className="metrics-group">
            <div className="metrics-group__title">Doanh thu</div>
            <div className="metric">
              <span className="metric__label">📊 Doanh thu ca (dự kiến)</span>
              <span className="metric__value">{metrics ? formatVND(metrics.shift_revenue) : '…'}</span>
            </div>
            <div className="metric">
              <span className="metric__label">Số đơn</span>
              <span className="metric__value">{metrics ? metrics.order_count : '…'}</span>
            </div>
          </div>

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
            {summary && summary.incomeCash > 0 && (
              <div className="summary__row">
                <span>＋ Thu khác (tiền mặt)</span>
                <span>{formatVND(summary.incomeCash)}</span>
              </div>
            )}
            {summary && summary.expenseCash > 0 && (
              <div className="summary__row">
                <span>－ Chi (tiền mặt)</span>
                <span>{formatVND(summary.expenseCash)}</span>
              </div>
            )}
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

          {/* Rút tiền nộp chủ (Stage 6.2) — lấy ra khỏi két SAU đối soát. */}
          <label className="field">
            <span>Rút nộp chủ (tiền lấy ra khỏi két)</span>
            <MoneyInput value={handover} onChange={setHandover} />
          </label>
          <div className={`cashleft ${handoverInvalid ? 'cashleft--bad' : ''}`}>
            <span>Tiền để lại ca sau</span>
            <strong>
              {actual === ''
                ? '—'
                : `${formatVND(actualNum)} − ${formatVND(handoverNum)} = ${formatVND(cashLeft)}`}
            </strong>
          </div>
          {handoverInvalid && (
            <p className="diff__note">⚠️ Tiền nộp chủ vượt quá tiền thực đếm.</p>
          )}

          <div className="row-actions">
            <button type="button" className="btn btn--ghost" onClick={() => setView('main')}>
              Quay lại
            </button>
            <button type="submit" className="btn btn--primary btn--lg" disabled={busy || actual === '' || handoverInvalid}>
              {busy ? 'Đang đóng…' : 'Xác nhận đóng ca'}
            </button>
          </div>
        </form>
      )}
    </div>
  )
}

// Màn kết quả sau khi đóng ca.
function ResultCard({ closed, onBack, onPrintHandover, onPrintReport }) {
  const diff = toNumber(closed.cash_difference)
  const level = diffLevel(diff)
  const handover = toNumber(closed.handover_to_owner)
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
        {toNumber(closed.total_income) > 0 && (
          <div className="summary__row">
            <span>＋ Thu khác (tiền mặt)</span>
            <span>{formatVND(closed.total_income)}</span>
          </div>
        )}
        {toNumber(closed.total_expense) > 0 && (
          <div className="summary__row">
            <span>－ Chi (tiền mặt)</span>
            <span>{formatVND(closed.total_expense)}</span>
          </div>
        )}
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

      {/* Rút nộp chủ + tiền để lại ca sau (Stage 6.2) */}
      <div className="summary">
        <div className="summary__row"><span>Rút nộp chủ</span><span>{formatVND(closed.handover_to_owner)}</span></div>
        <div className="summary__row summary__row--head"><span>Tiền để lại ca sau</span><span>{formatVND(closed.cash_left_for_next)}</span></div>
      </div>

      <div className="row-actions" style={{ marginTop: 12 }}>
        {handover > 0 && (
          <button className="btn btn--ghost btn--lg" onClick={onPrintHandover}>🧾 In biên nhận nộp chủ</button>
        )}
        <button className="btn btn--ghost btn--lg" onClick={onPrintReport}>🧾 In biên bản giao ca</button>
      </div>

      <button className="btn btn--primary btn--xl btn--block" style={{ marginTop: 10 }} onClick={onBack}>
        Về trang ca
      </button>
    </div>
  )
}
