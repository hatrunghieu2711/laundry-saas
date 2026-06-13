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

// Picker kiểu iOS: 2 cột cuộn dọc. Giờ (0-23) LOOP vô cực, phút 4 mốc 00/15/30/45.
// Cảm ứng (vuốt) + chuột (cuộn lăn / bấm item). Item giữa (dải cam) là đang chọn.
//
// Cách loop: nhân bản danh sách giờ REPEAT lần; SAU MỖI lần dừng cuộn luôn
// "silent-recenter" về bản GIỮA (giá trị lặp y hệt nên vô hình). Nhờ vậy người
// dùng luôn ở giữa, còn dư nhiều bản 2 phía → vuốt cả 2 chiều không bao giờ chạm
// đầu/cuối thật, 23 → 0 và 0 → 23 mượt.
const ITEM_H = 40 // khớp .wheel__item (CSS hiển thị 3 dòng, dòng giữa = chọn)
const REPEAT = 9 // số bản lặp cho cột loop (đủ dư cho flick mạnh)
const MIDDLE = 4 // bản giữa (0-indexed)

function Wheel({ values, valueIndex, onChange, loop = false, ariaLabel }) {
  const ref = useRef(null)
  const settle = useRef(0)
  const selfScroll = useRef(false) // đánh dấu thay đổi do chính wheel này gây ra
  const n = values.length
  const rendered = loop
    ? Array.from({ length: n * REPEAT }, (_, i) => values[i % n])
    : values

  const centerOf = (renderIndex) => renderIndex * ITEM_H

  // Căn item chọn vào giữa khi valueIndex đổi TỪ NGOÀI (mở modal / đổi ngày).
  // Bỏ qua nếu thay đổi do chính wheel cuộn (đã tự recenter trong settle).
  useEffect(() => {
    const el = ref.current
    if (!el) return
    if (selfScroll.current) {
      selfScroll.current = false
      return
    }
    el.scrollTop = centerOf(loop ? MIDDLE * n + valueIndex : valueIndex)
  }, [valueIndex, loop, n])

  const onScroll = () => {
    const el = ref.current
    if (!el) return
    clearTimeout(settle.current)
    settle.current = setTimeout(() => {
      let r = Math.round(el.scrollTop / ITEM_H)
      r = Math.max(0, Math.min(rendered.length - 1, r))
      const vi = ((r % n) + n) % n
      if (loop) {
        // Luôn kéo về bản giữa (vô hình) → còn dư 2 phía cho lần vuốt sau.
        el.scrollTop = centerOf(MIDDLE * n + vi)
      } else {
        el.scrollTop = centerOf(r) // snap đúng mốc
      }
      if (vi !== valueIndex) {
        selfScroll.current = true
        onChange(vi)
      }
    }, 80)
  }

  const handleClick = (renderIndex) => {
    onChange(((renderIndex % n) + n) % n)
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
            onClick={() => handleClick(i)}
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
          className={`chip chip--sm ${isToday ? 'chip--active' : ''}`}
          onClick={() => setDay(vnNowDay)}
        >
          Hôm nay
        </button>
        <button
          type="button"
          className={`chip chip--sm ${isTomorrow ? 'chip--active' : ''}`}
          onClick={() => setDay(addDaysVn(vnNowDay, 1))}
        >
          Ngày mai
        </button>
        {isFar && <span className="chip chip--sm chip--active">Ngày khác</span>}
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
          '⚠️ Giờ giao không được ở quá khứ.'
        ) : (
          <>
            Giao lúc: <strong>{formatPickupLong(value)}</strong>
          </>
        )}
      </div>
    </div>
  )
}
