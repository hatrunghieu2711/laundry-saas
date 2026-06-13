import { useEffect, useRef } from 'react'
import {
  QUARTERS,
  addDaysVn,
  combineVn,
  dateInputValueVn,
  formatPickupLong,
  getVnHour,
  getVnMinute,
  isPastVnWall,
  isSameDayVn,
  nearestQuarterIndex,
  parseDateInputVn,
  startOfDayVn,
} from '../lib/datetime'

// Picker kiểu iOS: 2 cột cuộn dọc. Giờ (0-23) LOOP vô cực (vuốt qua 23 → 0 cả 2
// chiều không kẹt); phút 4 mốc 00/15/30/45. Dùng được cảm ứng + chuột (cuộn lăn,
// bấm thẳng vào item). Item giữa (dải cam) là đang chọn.
const ITEM_H = 44 // khớp .wheel__item
const REPEAT = 7 // số bản lặp cho cột loop
const MIDDLE = 3 // bản giữa (0-indexed) — luôn giữ người dùng quanh đây

function Wheel({ values, valueIndex, onChange, loop = false, ariaLabel }) {
  const ref = useRef(null)
  const settle = useRef(0)
  const busy = useRef(false)
  const n = values.length
  const rendered = loop
    ? Array.from({ length: n * REPEAT }, (_, i) => values[i % n])
    : values

  // Căn item chọn vào giữa khi valueIndex đổi từ ngoài (mở modal / set default).
  useEffect(() => {
    const el = ref.current
    if (!el || busy.current) return
    const r = loop ? MIDDLE * n + valueIndex : valueIndex
    el.scrollTop = r * ITEM_H
  }, [valueIndex, loop, n])

  const onScroll = () => {
    const el = ref.current
    if (!el) return
    busy.current = true
    clearTimeout(settle.current)
    settle.current = setTimeout(() => {
      let r = Math.round(el.scrollTop / ITEM_H)
      r = Math.max(0, Math.min(rendered.length - 1, r))
      const vi = ((r % n) + n) % n
      // Loop: nếu cuộn tới gần biên (bản đầu/cuối), nhảy thầm về bản giữa
      // (giá trị lặp y hệt nên người dùng không thấy) → cuộn vô tận 2 chiều.
      if (loop && (r < n || r >= n * (REPEAT - 1))) {
        el.scrollTop = (MIDDLE * n + vi) * ITEM_H
      } else {
        el.scrollTop = r * ITEM_H // snap chính xác về mốc
      }
      busy.current = false
      if (vi !== valueIndex) onChange(vi)
    }, 110)
  }

  return (
    <div className="wheel">
      <div className="wheel__scroll" ref={ref} onScroll={onScroll} role="listbox" aria-label={ariaLabel}>
        <div className="wheel__pad" />
        {rendered.map((v, i) => (
          <button
            type="button"
            key={i}
            className={`wheel__item ${i % n === valueIndex ? 'wheel__item--sel' : ''}`}
            onClick={() => onChange(i % n)}
          >
            {v}
          </button>
        ))}
        <div className="wheel__pad" />
      </div>
    </div>
  )
}

const HOURS = Array.from({ length: 24 }, (_, h) => String(h).padStart(2, '0'))
const MINUTES = QUARTERS.map((m) => String(m).padStart(2, '0'))

// value: VN wall Date · onChange(VN wall Date). Default/turnaround do parent lo.
export default function WheelTimePicker({ value, onChange }) {
  const day = startOfDayVn(value)
  const hour = getVnHour(value)
  const minIndex = nearestQuarterIndex(getVnMinute(value))

  // Hôm nay theo giờ VN (không lệ thuộc cài đặt máy).
  const vnNowDay = startOfDayVn(new Date(Date.now() + 7 * 60 * 60 * 1000))
  const isToday = isSameDayVn(day, vnNowDay)
  const isTomorrow = isSameDayVn(day, addDaysVn(vnNowDay, 1))
  const isFar = !isToday && !isTomorrow

  const setHour = (h) => onChange(combineVn(value, h, QUARTERS[minIndex]))
  const setMinute = (mi) => onChange(combineVn(value, hour, QUARTERS[mi]))
  const setDay = (d) => onChange(combineVn(d, hour, QUARTERS[minIndex]))

  const past = isPastVnWall(value)

  return (
    <div className="pickup">
      <div className="pickup__dates">
        <button
          type="button"
          className={`chip ${isToday ? 'chip--active' : ''}`}
          onClick={() => setDay(vnNowDay)}
        >
          Hôm nay
        </button>
        <button
          type="button"
          className={`chip ${isTomorrow ? 'chip--active' : ''}`}
          onClick={() => setDay(addDaysVn(vnNowDay, 1))}
        >
          Ngày mai
        </button>
        {isFar && <span className="chip chip--active">Ngày khác</span>}
      </div>

      <input
        className="input pickup__cal"
        type="date"
        min={dateInputValueVn(vnNowDay)}
        value={dateInputValueVn(day)}
        onChange={(e) => e.target.value && setDay(parseDateInputVn(e.target.value))}
      />

      <div className="pickup__wheels">
        <Wheel values={HOURS} valueIndex={hour} onChange={setHour} loop ariaLabel="Giờ" />
        <span className="pickup__colon">:</span>
        <Wheel values={MINUTES} valueIndex={minIndex} onChange={setMinute} ariaLabel="Phút" />
      </div>

      <div className={`pickup__confirm ${past ? 'pickup__confirm--bad' : ''}`}>
        {past ? (
          '⚠️ Không thể hẹn giờ giao trong quá khứ.'
        ) : (
          <>
            Giờ giao: <strong>{formatPickupLong(value)}</strong>
          </>
        )}
      </div>
    </div>
  )
}
