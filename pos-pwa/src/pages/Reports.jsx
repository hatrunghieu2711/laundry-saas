import { useCallback, useEffect, useState } from 'react'
import { api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'

// Báo cáo cho chủ (Stage 6.3): 4 nhóm số liệu trong khoảng ngày + lọc chi nhánh.
// Doanh thu / Đã nộp chủ / Lệch két (cảnh báo) / Nợ chưa thu. Bản cơ bản — chỉ số,
// không biểu đồ, không Excel, không so sánh kỳ.

function ymd(d) {
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}
function daysAgo(n) {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return d
}
// "2026-06-11" → "11/06" (nhãn ngắn cho bảng theo ngày).
function shortDay(s) {
  const [, m, d] = s.split('-')
  return `${d}/${m}`
}
const signed = (n) => (n > 0 ? '+' : '') + formatVND(n)

// View thuần (không fetch) — tách để screenshot/preview render được (SSR không chạy effect).
export function ReportsView({
  branches, branchId, setBranchId, fromDate, setFromDate, toDate, setToDate, data, error,
}) {
  const branchName = (id) => {
    const b = branches.find((x) => x.id === id)
    return b ? `${b.code} · ${b.name}` : '—'
  }
  const cashDiff = data?.cash_diff
  const diffTotal = toNumber(cashDiff?.total)
  const hasDiff = cashDiff?.count > 0

  return (
    <div className="reports">
      {/* Bộ lọc: khoảng ngày + chi nhánh */}
      <div className="card reports__filters">
        <div className="reports__dates">
          <label className="field field--inline">
            <span>Từ ngày</span>
            <input className="input" type="date" value={fromDate} max={toDate}
              onChange={(e) => setFromDate(e.target.value)} />
          </label>
          <label className="field field--inline">
            <span>Đến ngày</span>
            <input className="input" type="date" value={toDate} min={fromDate}
              onChange={(e) => setToDate(e.target.value)} />
          </label>
        </div>
        <div className="branch-picker">
          <span className="branch-picker__label">Chi nhánh</span>
          <div className="branch-picker__chips">
            <button className={`chip ${!branchId ? 'chip--active' : ''}`} onClick={() => setBranchId(null)}>
              Tất cả
            </button>
            {branches.map((b) => (
              <button key={b.id} className={`chip ${branchId === b.id ? 'chip--active' : ''}`}
                onClick={() => setBranchId(b.id)}>
                {b.code} · {b.name}
              </button>
            ))}
          </div>
        </div>
      </div>

      {error && <div className="alert alert--error">{error}</div>}
      {data === undefined && <p className="shift__hint">Đang tải báo cáo…</p>}

      {data && (
        <>
          {/* 4 thẻ số lớn */}
          <div className="reports__cards">
            <div className="rcard rcard--revenue">
              <span className="rcard__label">Doanh thu</span>
              <strong className="rcard__value">{formatVND(data.revenue.total)}</strong>
            </div>
            <div className="rcard rcard--handover">
              <span className="rcard__label">Đã nộp chủ</span>
              <strong className="rcard__value">{formatVND(data.handover.total)}</strong>
              <span className="rcard__sub">{data.handover.count} lần</span>
            </div>
            <div className={`rcard ${hasDiff ? 'rcard--warn' : 'rcard--ok'}`}>
              <span className="rcard__label">Lệch két</span>
              <strong className="rcard__value">{hasDiff ? signed(diffTotal) : '0đ'}</strong>
              <span className="rcard__sub">
                {hasDiff ? `${cashDiff.count} ca lệch` : 'Tất cả ca khớp ✓'}
              </span>
            </div>
            <div className="rcard rcard--debt">
              <span className="rcard__label">Nợ chưa thu</span>
              <strong className="rcard__value">{formatVND(data.unpaid.total_outstanding)}</strong>
              <span className="rcard__sub">{data.unpaid.order_count} đơn</span>
            </div>
          </div>

          {/* Doanh thu theo ngày */}
          <div className="card">
            <h3 className="reports__h">Doanh thu theo ngày</h3>
            {data.revenue.by_day.length === 0 ? (
              <p className="shift__hint">Không có doanh thu trong khoảng này.</p>
            ) : (
              <table className="reports__table">
                <tbody>
                  {data.revenue.by_day.map((d) => (
                    <tr key={d.date}>
                      <td>{shortDay(d.date)}</td>
                      <td className="reports__num">{formatVND(d.revenue)}</td>
                    </tr>
                  ))}
                  <tr className="reports__table-total">
                    <td>Tổng</td>
                    <td className="reports__num">{formatVND(data.revenue.total)}</td>
                  </tr>
                </tbody>
              </table>
            )}
            {data.revenue.by_branch.length > 1 && (
              <table className="reports__table" style={{ marginTop: 8 }}>
                <tbody>
                  {data.revenue.by_branch.map((b) => (
                    <tr key={b.branch_id}>
                      <td>{b.branch_name || branchName(b.branch_id)}</td>
                      <td className="reports__num">{formatVND(b.revenue)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            )}
          </div>

          {/* Lệch quỹ ca (đầu + cuối) — cảnh báo (Stage 6.57: gồm cả lệch đầu ca) */}
          <div className="card">
            <h3 className="reports__h">Lệch quỹ ca (đầu + cuối) {hasDiff && <span className="reports__warn-tag">⚠ thất thoát</span>}</h3>
            {!hasDiff ? (
              <p className="reports__ok">Tất cả ca khớp ✓ ({cashDiff.matched_count} ca)</p>
            ) : (
              <ul className="reports__list">
                {cashDiff.rows.map((r) => {
                  const d = toNumber(r.cash_difference)
                  const od = r.opening_diff != null ? toNumber(r.opening_diff) : null
                  return (
                    <li key={r.shift_id} className="reports__list-item reports__list-item--warn">
                      <div className="reports__list-main">
                        <span className="reports__list-title">{branchName(r.branch_id)}</span>
                        <span className="reports__list-meta">
                          {r.staff_name || '—'} · {formatDateTime(r.closed_at)}
                        </span>
                        {od !== null && (
                          <span className="reports__diff">
                            <span className="reports__diff-lbl">Đầu ca</span>
                            <strong className={od < 0 ? 'reports__neg' : 'reports__over'}>{signed(od)}</strong>
                            {r.opening_diff_reason && <span className="reports__diff-reason">{r.opening_diff_reason}</span>}
                          </span>
                        )}
                        {d !== 0 && (
                          <span className="reports__diff">
                            <span className="reports__diff-lbl">Cuối ca</span>
                            <strong className={d < 0 ? 'reports__neg' : 'reports__over'}>{signed(d)}</strong>
                            {r.cash_diff_reason && <span className="reports__diff-reason">{r.cash_diff_reason}</span>}
                          </span>
                        )}
                      </div>
                    </li>
                  )
                })}
              </ul>
            )}
          </div>

          {/* Đã nộp chủ */}
          <div className="card">
            <h3 className="reports__h">Đã nộp chủ ({data.handover.count})</h3>
            {data.handover.rows.length === 0 ? (
              <p className="shift__hint">Chưa có khoản nộp chủ trong khoảng này.</p>
            ) : (
              <ul className="reports__list">
                {data.handover.rows.map((r) => (
                  <li key={r.shift_id} className="reports__list-item">
                    <div className="reports__list-main">
                      <span className="reports__list-title">{branchName(r.branch_id)}</span>
                      <span className="reports__list-meta">
                        {r.staff_name || '—'} · {formatDateTime(r.closed_at)}
                      </span>
                    </div>
                    <strong>{formatVND(r.amount)}</strong>
                  </li>
                ))}
              </ul>
            )}
          </div>

          {/* Nợ chưa thu */}
          <div className="card">
            <h3 className="reports__h">Nợ chưa thu</h3>
            <div className="summary__row summary__row--head">
              <span>{data.unpaid.order_count} đơn còn nợ</span>
              <strong className="reports__neg">{formatVND(data.unpaid.total_outstanding)}</strong>
            </div>
            <p className="reports__hint">Đơn tạo trong khoảng còn nợ (tính tới hiện tại).</p>
          </div>
        </>
      )}
    </div>
  )
}

export default function Reports() {
  const [branches, setBranches] = useState([])
  const [branchId, setBranchId] = useState(null) // null = tất cả chi nhánh
  const [fromDate, setFromDate] = useState(ymd(daysAgo(6))) // mặc định 7 ngày gần nhất
  const [toDate, setToDate] = useState(ymd(new Date()))
  const [data, setData] = useState(undefined) // undefined=loading, null=lỗi, obj
  const [error, setError] = useState('')

  useEffect(() => {
    api
      .get('/branches?limit=200')
      .then((p) => setBranches(p.items.filter((b) => b.status === 'active')))
      .catch(() => {})
  }, [])

  const load = useCallback(async () => {
    setError('')
    setData(undefined)
    try {
      let q = `?from_date=${fromDate}&to_date=${toDate}`
      if (branchId) q += `&branch_id=${branchId}`
      setData(await api.get(`/reports/owner-summary${q}`))
    } catch (err) {
      setData(null)
      setError(err?.message || 'Không tải được báo cáo')
    }
  }, [fromDate, toDate, branchId])

  useEffect(() => {
    load()
  }, [load])

  return (
    <ReportsView
      branches={branches} branchId={branchId} setBranchId={setBranchId}
      fromDate={fromDate} setFromDate={setFromDate} toDate={toDate} setToDate={setToDate}
      data={data} error={error}
    />
  )
}
