// Helper ngày-giờ cho giờ hẹn giao (pickup_at). Làm việc theo GIỜ ĐỊA PHƯƠNG;
// gửi backend bằng toISOString() (UTC) — backend nhận tz-aware.

export const QUARTERS = [0, 15, 30, 45] // bước phút 15'

function pad(n) {
  return String(n).padStart(2, '0')
}

export function startOfDay(d) {
  const x = new Date(d)
  x.setHours(0, 0, 0, 0)
  return x
}

export function addDays(d, n) {
  const x = new Date(d)
  x.setDate(x.getDate() + n)
  return x
}

// Ghép ngày + giờ + phút thành một Date (giờ địa phương).
export function combine(day, hour, minute) {
  const x = new Date(day)
  x.setHours(hour, minute, 0, 0)
  return x
}

export function isSameDay(a, b) {
  return (
    a.getFullYear() === b.getFullYear() &&
    a.getMonth() === b.getMonth() &&
    a.getDate() === b.getDate()
  )
}

// Vị trí mốc 15' gần nhất với số phút bất kỳ.
export function nearestQuarterIndex(minute) {
  let best = 0
  let bestDiff = Infinity
  QUARTERS.forEach((q, i) => {
    const diff = Math.abs(q - minute)
    if (diff < bestDiff) {
      bestDiff = diff
      best = i
    }
  })
  return best
}

// Gợi ý mặc định: bây giờ + 4h (turnaround chuẩn), làm tròn LÊN mốc 15'.
export function defaultPickup(base = new Date()) {
  const d = new Date(base.getTime() + 4 * 60 * 60 * 1000)
  d.setSeconds(0, 0)
  const up = Math.ceil(d.getMinutes() / 15) * 15
  if (up === 60) d.setHours(d.getHours() + 1, 0, 0, 0)
  else d.setMinutes(up, 0, 0)
  return d
}

// "HH:MM ngày DD/MM" — dòng xác nhận khi tạo đơn.
export function formatPickupLong(d) {
  if (!d) return ''
  const x = d instanceof Date ? d : new Date(d)
  if (Number.isNaN(x.getTime())) return ''
  return `${pad(x.getHours())}:${pad(x.getMinutes())} ngày ${pad(x.getDate())}/${pad(x.getMonth() + 1)}`
}

// "HH:MM DD/MM" — phiếu in, thẻ bảng đơn (nhận Date hoặc ISO string).
export function formatPickupShort(value) {
  if (!value) return ''
  const d = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(d.getTime())) return ''
  return `${pad(d.getHours())}:${pad(d.getMinutes())} ${pad(d.getDate())}/${pad(d.getMonth() + 1)}`
}

// Giá trị cho <input type="date"> (YYYY-MM-DD theo giờ địa phương).
export function dateInputValue(d) {
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

export function parseDateInput(str) {
  const [y, m, day] = str.split('-').map(Number)
  return new Date(y, m - 1, day)
}
