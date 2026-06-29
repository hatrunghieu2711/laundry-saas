// ⚠️ TẠM (GĐ3) — chụp node bill → ảnh PNG để in printBitmap / kiểm layout.
// DÙNG DYNAMIC IMPORT html2canvas → KHÔNG vào bundle chính (chỉ tải khi bấm CHỤP/IN). Node phải
// HIỂN THỊ THẬT (off-screen left:-9999px), KHÔNG display:none.

async function _renderNode(node, scale) {
  const html2canvas = (await import('html2canvas')).default
  return html2canvas(node, {
    backgroundColor: '#fff', // tránh nền trong suốt → đen khi in bitmap
    scale, // 1 = đúng px CSS; >1 → raster nét hơn
    useCORS: true,
    logging: false,
  })
}

// Quét pixel: đếm số CỘT trắng liền mép TRÁI và PHẢI (ngưỡng <250 = có mực) → kiểm ảnh đối xứng.
function _scanBlankMargins(canvas) {
  const w = canvas.width
  const h = canvas.height
  if (!w || !h) return { left: 0, right: 0, content: 0 }
  const data = canvas.getContext('2d').getImageData(0, 0, w, h).data
  const colHasInk = (x) => {
    for (let y = 0; y < h; y++) {
      const i = (y * w + x) * 4
      if (data[i] < 250 || data[i + 1] < 250 || data[i + 2] < 250) return true
    }
    return false
  }
  let left = 0
  while (left < w && !colHasInk(left)) left++
  if (left === w) return { left: w, right: 0, content: 0 } // trắng hết
  let right = 0
  while (right < w && !colHasInk(w - 1 - right)) right++
  return { left, right, content: w - left - right }
}

// Chụp node (bill, hẹp hơn vùng in) rồi VẼ CANH GIỮA lên canvas đích rộng canvasWidth (= vùng in
// máy) → chừa LỀ ĐỆM trắng đều 2 bên (đệm dung sai: giấy xê dịch nhẹ vẫn không cắt/không lộ lệch).
// dx = (canvasWidth − billWidth)/2. analyze=true → kèm đo lề trắng trái/phải của ảnh cuối.
export async function captureNodeCentered(node, { scale = 1, canvasWidth, analyze = false } = {}) {
  if (!node) throw new Error('captureNodeCentered: node rỗng')
  const bill = await _renderNode(node, scale)
  const w = canvasWidth && canvasWidth > bill.width ? Math.round(canvasWidth) : bill.width
  let canvas = bill
  let dx = 0
  if (w > bill.width) {
    canvas = document.createElement('canvas')
    canvas.width = w
    canvas.height = bill.height
    const ctx = canvas.getContext('2d')
    ctx.fillStyle = '#fff'
    ctx.fillRect(0, 0, w, bill.height)
    dx = Math.round((w - bill.width) / 2)
    ctx.drawImage(bill, dx, 0)
  }
  const out = { dataUrl: canvas.toDataURL('image/png'), width: canvas.width, height: canvas.height, billWidth: bill.width, dx }
  if (analyze) Object.assign(out, _scanBlankMargins(canvas))
  return out
}
