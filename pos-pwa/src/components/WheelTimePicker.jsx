import { useEffect, useRef, useState } from 'react'
import {
  QUARTERS,
  addDays,
  combine,
  dateInputValue,
  formatPickupLong,
  isSameDay,
  nearestQuarterIndex,
  parseDateInput,
  startOfDay,
} from '../lib/datetime'

// Picker kiểu iOS: 2 cột cuộn dọc (giờ / phút), snap vào mốc, item giữa = đang chọn.
// Dùng được cả cảm ứng (vuốt) lẫn chuột (cuộn lăn + bấm thẳng vào item).
const ITEM_H = 44 // phải khớp .wheel__item trong index.css
const PAD_ITEMS = 2 // số item đệm mỗi đầu → hiển thị 5 dòng, dòng giữa là chọn

function WheelColumn({ values, index, onSelect, ariaLabel }) {
  const ref = useRef(null)
  const settle = useRef(0)
  const scrolling = useRef(false)

  // Căn item đang chọn vào giữa khi index đổi từ ngoài (không khi đang cuộn tay).
  useEffect(() => {
    const el = ref.current
    if (!el || scrolling.current) return
    el.scrollTop = index * ITEM_H
  }, [index])

  const handleScroll = () => {
    const el = ref.current
    if (!el) return
    scrolling.current = true
    clearTimeout(settle.current)
    settle.current = setTimeout(() => {
      const i = Math.max(0, Math.min(values.length - 1, Math.round(el.scrollTop / ITEM_H)))
      scrolling.current = false
      if (i !== index) onSelect(i)
      else el.scrollTop = i * ITEM_H // snap chính xác về mốc
    }, 110)
  }

  return (
    <div className="wheel">
      <div className="wheel__scroll" ref={ref} onScroll={handleScroll} role="listbox" aria-label={ariaLabel}>
        <div className="wheel__pad" />
        {values.map((v, i) => (
          <button
            type="button"
            key={v}
            className={`wheel__item ${i === index ? 'wheel__item--sel' : ''}`}
            onClick={() => onSelect(i)}
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

// value: Date (giờ địa phương) · onChange(Date). Mặc định/validate do parent lo;
// picker tự cảnh báo nếu chọn quá khứ.
export default function WheelTimePicker({ value, onChange }) {
  const [showCal, setShowCal] = useState(false)
  const now = new Date()

  const day = startOfDay(value)
  const hour = value.getHours()
  const minIndex = nearestQuarterIndex(value.getMinutes())

  const today = startOfDay(now)
  const tomorrow = addDays(today, 1)
  const isToday = isSameDay(day, today)
  const isTomorrow = isSameDay(day, tomorrow)
  const isFar = !isToday && !isTomorrow

  const setHour = (h) => onChange(combine(day, h, QUARTERS[minIndex]))
  const setMinute = (mi) => onChange(combine(day, hour, QUARTERS[mi]))
  const setDay = (d) => onChange(combine(d, hour, QUARTERS[minIndex]))

  const isPast = value.getTime() <= now.getTime()

  return (
    <div className="pickup">
      <div className="pickup__dates">
        <button
          type="button"
          className={`chip ${isToday ? 'chip--active' : ''}`}
          onClick={() => {
            setShowCal(false)
            setDay(today)
          }}
        >
          Hôm nay
        </button>
        <button
          type="button"
          className={`chip ${isTomorrow ? 'chip--active' : ''}`}
          onClick={() => {
            setShowCal(false)
            setDay(tomorrow)
          }}
        >
          Ngày mai
        </button>
        <button
          type="button"
          className={`chip ${isFar || showCal ? 'chip--active' : ''}`}
          onClick={() => setShowCal((s) => !s)}
        >
          📅 Chọn ngày
        </button>
      </div>

      {(showCal || isFar) && (
        <input
          className="input pickup__cal"
          type="date"
          min={dateInputValue(today)}
          value={dateInputValue(day)}
          onChange={(e) => e.target.value && setDay(parseDateInput(e.target.value))}
        />
      )}

      <div className="pickup__wheels">
        <WheelColumn values={HOURS} index={hour} onSelect={setHour} ariaLabel="Giờ" />
        <span className="pickup__colon">:</span>
        <WheelColumn values={MINUTES} index={minIndex} onSelect={setMinute} ariaLabel="Phút" />
      </div>

      <div className={`pickup__confirm ${isPast ? 'pickup__confirm--bad' : ''}`}>
        {isPast ? (
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
