import { useCallback, useEffect, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import MoneyInput from '../components/MoneyInput'
import ShiftSlip from '../components/ShiftSlip'
import ShiftEmpty from '../components/ShiftEmpty'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { useShift } from '../context/ShiftContext'
import { ApiError, api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'
import { nativePrintActive } from '../lib/platform'
import { nativePrintShift } from '../lib/nativePrintStore'

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
  const { setShiftOpen } = useShift() // đồng bộ nhãn tab "Ca" (6.71)
  const [shift, setShift] = useState(undefined) // undefined=loading, null=chưa có ca, obj=đang mở
  const [summary, setSummary] = useState(null) // client-side (cho form đóng ca)
  const [metrics, setMetrics] = useState(null) // realtime từ GET /shifts/{id}/summary (Stage 6.1)
  const [refreshing, setRefreshing] = useState(false)
  const [view, setView] = useState('main') // main | open | close | result
  const [opening, setOpening] = useState('')
  const [openSuggestion, setOpenSuggestion] = useState(0) // gợi ý đầu ca (Stage 6.2)
  const [openHasPrev, setOpenHasPrev] = useState(false)   // có ca trước → đối chiếu (6.55)
  const [openReason, setOpenReason] = useState('')        // lý do lệch đầu ca
  const [openReasonErr, setOpenReasonErr] = useState(false) // lỗi thiếu lý do → hiện DƯỚI ô
  const [actual, setActual] = useState('')
  const [handover, setHandover] = useState('') // rút nộp chủ (Stage 6.2)
  const [handoverErr, setHandoverErr] = useState(false) // Stage 6.35: lỗi "rút nộp chủ trống" — hiện DƯỚI ô
  const [diffReason, setDiffReason] = useState('') // lý do lệch tiền (Stage 6.32; bắt buộc khi lệch≠0)
  const [reasonErr, setReasonErr] = useState(false) // Stage 6.36: lỗi "thiếu lý do lệch" — hiện DƯỚI ô
  const [closed, setClosed] = useState(null)
  const [printSlip, setPrintSlip] = useState(null) // 'handover' | 'report'
  const [lastClosed, setLastClosed] = useState(null) // Stage 6.37: ca đóng gần nhất (xem/in lại từ DB)
  const [reopenAsk, setReopenAsk] = useState(false)  // Stage 6.37: popup xác nhận mở lại ca
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
    setLastClosed(null)
    if (isOwner && !branchId) {
      setShift(undefined)
      return
    }
    setShift(undefined)
    const q = isOwner ? `?branch_id=${branchId}` : ''
    try {
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
        // Có ca đóng gần nhất? → cho xem/in lại + mở lại (đọc từ DB, không phải state tạm).
        try {
          const lc = await api.get(`/shifts/latest-closed${q}`)
          setLastClosed(lc)
        } catch {
          setLastClosed(null)
        }
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
    setOpenReason(''); setOpenReasonErr(false)
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      const s = await api.get(`/shifts/opening-suggestion${q}`)
      const sug = toNumber(s.suggested_opening_cash)
      setOpenSuggestion(sug)
      setOpenHasPrev(!!s.has_previous)
      setOpening(sug > 0 ? String(sug) : '')
    } catch {
      setOpenSuggestion(0)
      setOpenHasPrev(false)
    }
    setView('open')
  }

  // In phiếu giao ca. Native: printBitmap (T2 không crash). Web: window.print như cũ.
  useEffect(() => {
    if (!printSlip) return undefined
    if (nativePrintActive()) {
      nativePrintShift(printSlip, closed, branchName) // closed/branchName: ref trong callback (sau render)
      setPrintSlip(null)
      return undefined
    }
    const t = setTimeout(() => {
      window.print()
      setPrintSlip(null)
    }, 150)
    return () => clearTimeout(t)
  }, [printSlip])

  const submitOpen = async (e) => {
    e.preventDefault()
    // Lệch đầu ca (so tiền để lại ca trước) → BẮT lý do (đai an toàn FE; backend cũng enforce).
    const openDiff = openHasPrev && toNumber(opening) !== openSuggestion
    if (openDiff && !openReason.trim()) {
      setOpenReasonErr(true)
      return
    }
    setBusy(true)
    setError('')
    setOpenReasonErr(false)
    try {
      const body = { opening_cash: toNumber(opening) }
      if (isOwner) body.branch_id = branchId
      if (openDiff) body.opening_diff_reason = openReason.trim()
      await api.post('/shifts/open', body)
      setShiftOpen(true) // 6.71: nhãn tab → "Đóng ca"
      setOpening(''); setOpenReason('')
      setView('main')
      await loadCurrent()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'SHIFT_ALREADY_OPEN') {
        setError('Chi nhánh đang có ca mở.')
        await loadCurrent()
      } else if (err instanceof ApiError && err.code === 'OPENING_DIFF_REASON_REQUIRED') {
        setOpenReasonErr(true) // hiện lỗi DƯỚI ô lý do, không ở đầu màn
      } else {
        setError(err?.message || 'Không mở được ca, thử lại.')
      }
    } finally {
      setBusy(false)
    }
  }

  const submitClose = async (e) => {
    e.preventDefault()
    // Rút nộp chủ BẮT BUỘC nhập chủ động (kể cả 0). Lỗi hiện NGAY DƯỚI Ô (không ở đầu màn).
    if (handover === '') {
      setHandoverErr(true)
      return
    }
    const handoverNum = toNumber(handover)
    if (handoverNum > toNumber(actual)) {
      setError('Tiền nộp chủ không được vượt quá tiền thực đếm.')
      return
    }
    // Có lệch tiền (thực đếm ≠ dự kiến) → BẮT BUỘC lý do (chống bỏ qua lệch quỹ).
    const diff = toNumber(actual) - expected
    if (diff !== 0 && !diffReason.trim()) {
      setReasonErr(true) // lỗi hiện NGAY DƯỚI ô (không ở đầu màn)
      return
    }
    setBusy(true)
    setError('')
    try {
      const res = await api.post(`/shifts/${shift.id}/close`, {
        closing_cash_actual: toNumber(actual),
        handover_to_owner: handoverNum,
        // Stage 6.32: gửi lý do lệch (forward-compat). BACKEND CHƯA có cột cash_diff_reason
        // → hiện bị BỎ QUA (chưa lưu) cho tới khi thêm cột+schema+service. Báo để xử riêng.
        cash_diff_reason: diff !== 0 ? diffReason.trim() : null,
      })
      setClosed(res)
      setShiftOpen(false) // 6.71: nhãn tab → "Mở ca"
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

  // Stage 6.37: xem lại ca vừa đóng (đọc từ DB) → in lại biên nhận bất cứ lúc nào.
  const viewLastClosed = () => {
    if (!lastClosed) return
    setClosed(lastClosed)
    setView('result')
  }

  // Stage 6.37: mở lại ca (đã xác nhận ở popup) → ca về 'open', thu thêm rồi đóng lại.
  const doReopen = async () => {
    if (!closed) return
    setBusy(true)
    setError('')
    try {
      await api.post(`/shifts/${closed.id}/reopen`)
      setShiftOpen(true) // 6.71: mở lại ca → nhãn tab "Đóng ca"
      setReopenAsk(false)
      setClosed(null)
      setView('main')
      await loadCurrent()
    } catch (err) {
      setReopenAsk(false)
      setError(err instanceof ApiError ? err.message : 'Không mở lại được ca')
    } finally {
      setBusy(false)
    }
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
          onReopen={() => setReopenAsk(true)}
        />
      )}

      {/* Portal in phiếu giao ca (ẩn trên màn, hiện khi @media print). */}
      <ShiftSlip kind={printSlip} shift={closed} branchName={branchName} />

      {/* ── Popup xác nhận MỞ LẠI CA (Stage 6.37) ── */}
      {reopenAsk && (
        <div className="modal-overlay modal-overlay--top" role="dialog" aria-modal="true">
          <div className="panel panel--modal">
            <div className="panel__head"><span className="panel__title">Mở lại ca</span></div>
            <div className="panel__body">
              <div className="panel__group">
                <p className="panel__hint">
                  Mở lại ca để thu thêm? Số chốt cũ sẽ được tính lại khi đóng lại. Thao tác
                  này được GHI LOG (ai, lúc nào).
                </p>
              </div>
            </div>
            <div className="panel__foot">
              <button className="btn btn--ghost" onClick={() => setReopenAsk(false)} disabled={busy}>
                Đóng
              </button>
              <button className="btn btn--warn" onClick={doReopen} disabled={busy}>
                {busy ? 'Đang mở…' : 'Mở lại ca'}
              </button>
            </div>
          </div>
        </div>
      )}

      {/* ── ĐANG TẢI ── */}
      {view === 'main' && shift === undefined && branchId && (
        <p className="shift__hint">Đang tải ca…</p>
      )}

      {/* ── CHƯA CÓ CA → MỞ CA ── */}
      {view === 'main' && shift === null && (!isOwner || branchId) && (
        <ShiftEmpty>
          <p>Chưa có ca nào đang mở.</p>
          <button className="btn btn--primary btn--xl btn--block" onClick={startOpen}>
            MỞ CA
          </button>
          {lastClosed && (
            <button
              className="btn btn--ghost btn--block"
              style={{ marginTop: 10 }}
              onClick={viewLastClosed}
            >
              Xem ca vừa đóng
            </button>
          )}
        </ShiftEmpty>
      )}

      {/* ── FORM MỞ CA ── */}
      {view === 'open' && (
        <form className="shift__card" onSubmit={submitOpen}>
          <h2 className="shift__card-title">Mở ca</h2>
          {openSuggestion > 0 && (
            <p className="shift__hint">
              Gợi ý: ca trước để lại <strong>{formatVND(openSuggestion)}</strong> — đếm lại trong két rồi xác nhận/sửa.
            </p>
          )}
          <label className="field">
            <span>Tiền mặt đầu ca trong két</span>
            <MoneyInput value={opening} onChange={setOpening} autoFocus required />
          </label>
          {openHasPrev && opening !== '' && toNumber(opening) !== openSuggestion && (
            <>
              <p className="shift__warn">
                Lệch {formatVND(toNumber(opening) - openSuggestion)} so với tiền để lại ca trước ({formatVND(openSuggestion)}). Đếm lại trước khi xác nhận.
              </p>
              <label className="field">
                <span>Lý do lệch (bắt buộc)</span>
                <input
                  className="input"
                  value={openReason}
                  onChange={(e) => { setOpenReason(e.target.value); setOpenReasonErr(false) }}
                  placeholder="VD: bù quỹ đầu ca / thiếu chưa rõ…"
                />
                {openReasonErr && <span className="field-note field-note--err">Bắt buộc nhập lý do khi tiền đầu ca lệch.</span>}
              </label>
            </>
          )}
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
        <div className="shift__card">
          <div className="shift__head">
            <div className="badge badge--open">● Ca đang mở</div>
            <button className="btn btn--ghost btn--sm" onClick={refresh} disabled={refreshing}>
              {refreshing ? '…' : 'Làm mới'}
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
              <span className="metric__label">Tiền mặt trong két</span>
              <span className="metric__value">{metrics ? formatVND(metrics.cash_in_drawer) : '…'}</span>
            </div>
            <div className="metric">
              <span className="metric__label">Chuyển khoản / QR</span>
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
              <span className="metric__label">Doanh thu ca (dự kiến)</span>
              <span className="metric__value">{metrics ? formatVND(metrics.shift_revenue) : '…'}</span>
            </div>
            <div className="metric">
              <span className="metric__label">Số đơn</span>
              <span className="metric__value">{metrics ? metrics.order_count : '…'}</span>
            </div>
          </div>

          <button
            className="btn btn--primary btn--block shift__cta"
            onClick={() => navigate('/orders/new')}
          >
            + Tạo đơn
          </button>
          <div className="shift__btnrow">
            <button className="btn btn--ghost btn--sm" onClick={() => navigate('/board')}>
              Đơn hàng
            </button>
            <button className="btn btn--ghost btn--sm" onClick={() => setView('close')}>
              Đóng ca
            </button>
          </div>
        </div>
      )}

      {/* ── FORM ĐÓNG CA ── */}
      {view === 'close' && shift && (
        <form className="shift__card" onSubmit={submitClose}>
          <h2 className="shift__card-title">Đóng ca</h2>

          <div className="summary">
            <div className="summary__row summary__row--head">
              <span>Đã thu trong ca</span>
              <span>{summary ? `${summary.ordersCount} đơn` : '…'}</span>
            </div>
            {/* Stage 6.35: bỏ COD (chưa có chức năng); gộp Chuyển khoản + QR thành 1 dòng. */}
            <div className="summary__row">
              <span>Tiền mặt</span>
              <span>{summary ? formatVND(summary.totals.cash) : '…'}</span>
            </div>
            <div className="summary__row">
              <span>Chuyển khoản & QR</span>
              <span>{summary ? formatVND(summary.totals.transfer + summary.totals.qr) : '…'}</span>
            </div>
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
            <MoneyInput
              value={actual}
              onChange={(v) => { setActual(v); if (reasonErr) setReasonErr(false) }}
              autoFocus
              required
            />
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
            {level === 'ok' && <p className="diff__note">Khớp két</p>}
            {(level === 'warn' || level === 'danger') && (
              <p className="diff__note">Lệch tiền, kiểm đếm lại trước khi xác nhận</p>
            )}
          </div>

          {/* Lý do lệch tiền — BẮT BUỘC khi chênh lệch ≠ 0 (Stage 6.32). Khớp két → không hiện. */}
          {(level === 'warn' || level === 'danger') && (
            <label className="field">
              <span>Lý do lệch tiền (bắt buộc)</span>
              <textarea
                className="input"
                rows={2}
                value={diffReason}
                onChange={(e) => { setDiffReason(e.target.value); if (reasonErr) setReasonErr(false) }}
                placeholder="VD: thối nhầm cho khách / chưa ghi 1 khoản chi…"
              />
              {reasonErr && (
                <span className="field-note field-note--err">Vui lòng nhập lý do lệch tiền.</span>
              )}
            </label>
          )}

          {/* Rút tiền nộp chủ (Stage 6.2) — lấy ra khỏi két SAU đối soát. */}
          <label className="field">
            <span>Rút nộp chủ (tiền lấy ra khỏi két)</span>
            <MoneyInput
              value={handover}
              onChange={(v) => { setHandover(v); if (handoverErr) setHandoverErr(false) }}
            />
            <span className={`field-note ${handoverErr ? 'field-note--err' : ''}`}>
              {handoverErr
                ? 'Vui lòng nhập số tiền nộp chủ (nhập 0 nếu không rút).'
                : 'Nhập 0 nếu không rút tiền nộp chủ.'}
            </span>
          </label>
          <div className={`cashleft ${handoverInvalid ? 'cashleft--bad' : ''}`}>
            <div className="cashleft__main">
              <span>Tiền để lại ca sau</span>
              <strong>{actual === '' ? '—' : formatVND(cashLeft)}</strong>
            </div>
            {actual !== '' && (
              <div className="cashleft__calc">
                {formatVND(actualNum)} − {formatVND(handoverNum)}
              </div>
            )}
          </div>
          {handoverInvalid && (
            <p className="diff__note">Tiền nộp chủ vượt quá tiền thực đếm.</p>
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
function ResultCard({ closed, onBack, onPrintHandover, onPrintReport, onReopen }) {
  const diff = toNumber(closed.cash_difference)
  const level = diffLevel(diff)
  const handover = toNumber(closed.handover_to_owner)
  return (
    <div className="shift__card">
      <h2 className="shift__card-title shift__done-title">
        <svg className="pay__check" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>
        Đã đóng ca
      </h2>
      {closed.reopen_count > 0 && (
        <p className="field-note field-note--err">Ca này đã mở lại {closed.reopen_count} lần</p>
      )}
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

      {/* Lệch ĐẦU ca (Stage 6.56) — cạnh lệch cuối ca; chỉ hiện khi ≠0. Thiếu=đỏ / thừa=amber. */}
      {closed.opening_diff != null && toNumber(closed.opening_diff) !== 0 && (
        <div className={`odiff ${toNumber(closed.opening_diff) < 0 ? 'odiff--short' : 'odiff--over'}`}>
          <div className="odiff__line">
            <span>Lệch đầu ca</span>
            <strong>{`${toNumber(closed.opening_diff) > 0 ? '+' : ''}${formatVND(closed.opening_diff)}`}</strong>
          </div>
          {closed.opening_diff_reason && <div className="odiff__reason">Lý do: {closed.opening_diff_reason}</div>}
        </div>
      )}

      {/* Rút nộp chủ + tiền để lại ca sau (Stage 6.2) */}
      <div className="summary">
        <div className="summary__row"><span>Rút nộp chủ</span><span>{formatVND(closed.handover_to_owner)}</span></div>
        <div className="summary__row summary__row--head"><span>Tiền để lại ca sau</span><span>{formatVND(closed.cash_left_for_next)}</span></div>
      </div>

      <div className="row-actions" style={{ marginTop: 12 }}>
        {handover > 0 && (
          <button className="btn btn--ghost btn--lg" onClick={onPrintHandover}>In biên nhận nộp chủ</button>
        )}
        <button className="btn btn--ghost btn--lg" onClick={onPrintReport}>In biên bản giao ca</button>
      </div>

      {onReopen && (
        <button className="btn btn--ghost btn--block shift__reopen" style={{ marginTop: 10 }} onClick={onReopen}>
          Mở lại ca
        </button>
      )}
      <button className="btn btn--primary btn--xl btn--block" style={{ marginTop: 10 }} onClick={onBack}>
        Về trang ca
      </button>
    </div>
  )
}
