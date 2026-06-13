// Helper ngày-giờ cho giờ hẹn giao (pickup_at).
//
// LỖI ĐÃ SỬA (Stage 3.8): trước đây dùng giờ LOCAL của trình duyệt — nếu máy POS
// để múi UTC thì giờ nhân viên chọn lệch 7h thành quá khứ → 422.
// Nay CỐ ĐỊNH theo giờ Việt Nam (UTC+7), không phụ thuộc cài đặt máy:
//   - "VN wall-clock Date": một Date mà các trường UTC của nó MÃ HOÁ giờ VN
//     (vd 16:30 VN → Date có getUTCHours()===16). Picker thao tác trên loại này.
//   - Khi gửi backend: đổi VN wall → instant thực (trừ 7h) rồi toISOString()
//     → 16:30 VN ⇒ "09:30Z" cùng ngày (KHÔNG quá khứ).

const VN_OFFSET_MS = 7 * 60 * 60 * 1000
export const QUARTERS = [0, 15, 30, 45] // bước phút 15'

const pad = (n) => String(n).padStart(2, '0')

// instant thực → VN wall (đọc bằng getUTC*)
function toVnWall(instant) {
  return new Date(instant.getTime() + VN_OFFSET_MS)
}
// VN wall → instant thực (UTC)
function wallToInstant(wall) {
  return new Date(wall.getTime() - VN_OFFSET_MS)
}

export function nowVnWall() {
  return toVnWall(new Date())
}

export function startOfDayVn(wall) {
  const x = new Date(wall.getTime())
  x.setUTCHours(0, 0, 0, 0)
  return x
}

export function addDaysVn(wall, n) {
  const x = new Date(wall.getTime())
  x.setUTCDate(x.getUTCDate() + n)
  return x
}

export function isSameDayVn(a, b) {
  return (
    a.getUTCFullYear() === b.getUTCFullYear() &&
    a.getUTCMonth() === b.getUTCMonth() &&
    a.getUTCDate() === b.getUTCDate()
  )
}

// Ghép ngày (lấy từ dayWall) + giờ + phút → VN wall mới.
export function combineVn(dayWall, hour, minute) {
  const x = new Date(dayWall.getTime())
  x.setUTCHours(hour, minute, 0, 0)
  return x
}

export const getVnHour = (wall) => wall.getUTCHours()
export const getVnMinute = (wall) => wall.getUTCMinutes()

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

// Gợi ý: bây giờ (VN) + turnaround giờ, làm tròn LÊN mốc 15'.
export function defaultPickupVnWall(turnaroundHours = 4) {
  const w = new Date(nowVnWall().getTime() + turnaroundHours * 60 * 60 * 1000)
  w.setUTCSeconds(0, 0)
  const up = Math.ceil(w.getUTCMinutes() / 15) * 15
  if (up === 60) w.setUTCHours(w.getUTCHours() + 1, 0, 0, 0)
  else w.setUTCMinutes(up, 0, 0)
  return w
}

// VN wall → ISO UTC để gửi backend.
export function vnWallToISO(wall) {
  return wallToInstant(wall).toISOString()
}

export function isPastVnWall(wall) {
  return wallToInstant(wall).getTime() <= Date.now()
}

// "HH:MM ngày DD/MM" từ VN wall (dùng trong picker).
export function formatPickupLong(wall) {
  if (!wall) return ''
  return `${pad(wall.getUTCHours())}:${pad(wall.getUTCMinutes())} ngày ${pad(
    wall.getUTCDate(),
  )}/${pad(wall.getUTCMonth() + 1)}`
}

// "HH:MM DD/MM" từ instant thực (ISO/Date backend) → hiển thị giờ VN.
export function formatPickupShort(value) {
  if (!value) return ''
  const inst = value instanceof Date ? value : new Date(value)
  if (Number.isNaN(inst.getTime())) return ''
  const w = toVnWall(inst)
  return `${pad(w.getUTCHours())}:${pad(w.getUTCMinutes())} ${pad(w.getUTCDate())}/${pad(
    w.getUTCMonth() + 1,
  )}`
}

// <input type="date"> theo giờ VN.
export function dateInputValueVn(wall) {
  return `${wall.getUTCFullYear()}-${pad(wall.getUTCMonth() + 1)}-${pad(wall.getUTCDate())}`
}

export function parseDateInputVn(str) {
  const [y, m, d] = str.split('-').map(Number)
  return new Date(Date.UTC(y, m - 1, d, 0, 0, 0, 0))
}
