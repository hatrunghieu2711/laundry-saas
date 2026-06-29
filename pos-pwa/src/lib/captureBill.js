// Chụp node bill/nhãn/slip (off-screen 68mm) → ảnh PNG → in printBitmap (kênh native T2). DÙNG
// DYNAMIC IMPORT html2canvas → KHÔNG vào bundle chính (chỉ tải khi in native; PWA T1 không nặng).
// Node phải HIỂN THỊ THẬT (off-screen left:-9999px), KHÔNG display:none.
// ⚠️ Chỉ dùng cho NODE CHỤP NATIVE (NativePrintLayer). Portal T1/window.print KHÔNG đụng tới file này.

// ── XỬ LÝ LOGO ĐEN-TRẮNG (in nhiệt chỉ in đen) ───────────────────────────────────────────────
// Logo MÀU: máy in nhiệt tự chuyển đen-trắng → màu SÁNG (vàng/cam…) bị đẩy thành TRẮNG → MẤT logo.
// → Chủ động chuyển đen-trắng TRƯỚC khi in. 2 chế độ (đổi LOGO_MODE để test):
//   'alpha'     = MASK theo hình: pixel có hình (alpha đủ) → ĐEN, trong suốt → trắng. CHẮC cho logo
//                 MÀU/nền trong suốt (in ra ĐÚNG HÌNH DẠNG, không phụ thuộc sáng/tối). ⚠️ Nếu logo
//                 PNG nền ĐẶC (không trong suốt) → ra Ô ĐEN ĐẶC → đổi sang 'luminance'.
//   'luminance' = theo ĐỘ SÁNG: tối < ngưỡng → đen, sáng → trắng. Giữ chi tiết; hợp logo nền đặc/
//                 có chữ. ⚠️ Logo màu SÁNG → ra trắng hết (mất) → đổi sang 'alpha'.
const LOGO_MODE = 'alpha' // 'alpha' | 'luminance' — đổi để test
const LOGO_THRESHOLD = 140 // mode 'luminance': luminance < này → ĐEN. Tăng→nhiều đen hơn, giảm→ít.
const LOGO_ALPHA_THRESHOLD = 64 // alpha < này → coi là TRONG SUỐT → trắng (cả 2 mode).

// Chuyển canvas (đã vẽ logo) sang ĐEN-TRẮNG thuần tại chỗ. getImageData OK vì bitmap same-origin
// (origin-clean → không taint). Lỗi (taint) → bỏ qua, giữ canvas màu.
function _logoToBW(canvas, ctx) {
  try {
    const w = canvas.width
    const h = canvas.height
    if (!w || !h) return
    const imgData = ctx.getImageData(0, 0, w, h)
    const d = imgData.data
    for (let p = 0; p < d.length; p += 4) {
      const a = d[p + 3]
      let black
      if (a < LOGO_ALPHA_THRESHOLD) {
        black = false // trong suốt → nền giấy (trắng)
      } else if (LOGO_MODE === 'alpha') {
        black = true // có hình → ĐEN (bất kể màu) — chắc cho logo màu sáng
      } else {
        const lum = 0.299 * d[p] + 0.587 * d[p + 1] + 0.114 * d[p + 2]
        black = lum < LOGO_THRESHOLD
      }
      const v = black ? 0 : 255
      d[p] = v
      d[p + 1] = v
      d[p + 2] = v
      d[p + 3] = 255
    }
    ctx.putImageData(imgData, 0, 0)
  } catch {
    /* getImageData taint/lỗi → giữ canvas màu (vẫn vẽ được) */
  }
}

// Chờ <img> trong node load xong → để offsetWidth/naturalWidth (dùng cho sizes[] của _prepareLogo
// Bitmaps) hợp lệ trước khi đo. Ảnh lỗi/chậm → timeout (3s) vẫn tiếp (KHÔNG treo việc in).
function _waitImages(node, timeoutMs = 3000) {
  if (!node || typeof node.querySelectorAll !== 'function') return Promise.resolve()
  const imgs = Array.from(node.querySelectorAll('img'))
  const pending = imgs.filter((im) => !(im.complete && im.naturalWidth > 0))
  if (!pending.length) return Promise.resolve()
  return new Promise((resolve) => {
    let left = pending.length
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      resolve()
    }
    const one = () => {
      left -= 1
      if (left <= 0) finish()
    }
    pending.forEach((im) => {
      if (typeof im.decode === 'function') {
        im.decode().then(one, one)
      } else {
        im.addEventListener('load', one, { once: true })
        im.addEventListener('error', one, { once: true })
      }
    })
    setTimeout(finish, timeoutMs)
  })
}

// ⭐ Logo <img> bị html2canvas trong WebView Sunmi BỎ QUA (như QRCodeSVG trước đây). GIẢI: thay
// <img> bằng <canvas> ĐÃ VẼ SẴN logo (html2canvas chụp <canvas> đáng tin — tiền lệ QRCodeCanvas).
// Pre-fetch bitmap ở đây (async): fetch→blob→createImageBitmap (same-origin → origin-clean → drawImage
// KHÔNG taint). Trả mảng bitmaps[i] + sizes[i] (index-aligned với node.querySelectorAll('img')) để
// onclone (SYNC) vẽ canvas + thay <img> TRONG BẢN CLONE (clone không do React quản → replace an toàn).
async function _prepareLogoBitmaps(node, timeoutMs = 3000) {
  const all = node && node.querySelectorAll ? Array.from(node.querySelectorAll('img')) : []
  const bitmaps = new Array(all.length).fill(null)
  const sizes = new Array(all.length).fill(null)
  const targets = all.map((im, i) => ({ im, i })).filter(({ im }) => /^https?:/i.test(im.src || ''))
  if (!targets.length || typeof createImageBitmap !== 'function') return { bitmaps, sizes }
  const one = async ({ im, i }) => {
    sizes[i] = { w: im.offsetWidth || im.naturalWidth || 0, h: im.offsetHeight || im.naturalHeight || 0 }
    try {
      const resp = await fetch(im.src, { cache: 'force-cache' })
      if (!resp.ok) return
      const blob = await resp.blob()
      bitmaps[i] = await createImageBitmap(blob) // blob same-origin → bitmap origin-clean (không taint)
    } catch {
      /* logo lỗi → bỏ qua, bill vẫn in */
    }
  }
  await Promise.race([
    Promise.all(targets.map((t) => one(t))),
    new Promise((res) => setTimeout(res, timeoutMs)),
  ])
  return { bitmaps, sizes }
}

async function _renderNode(node, scale) {
  await _waitImages(node)
  const { bitmaps, sizes } = await _prepareLogoBitmaps(node)
  const html2canvas = (await import('html2canvas')).default
  try {
    return await html2canvas(node, {
      backgroundColor: '#fff', // tránh nền trong suốt → đen khi in bitmap
      scale, // 1 = đúng px CSS; >1 → raster nét hơn
      useCORS: true,
      imageTimeout: 4000,
      logging: false,
      // html2canvas render BẢN CLONE → THAY mỗi <img> logo bằng <canvas> đã vẽ bitmap (sync). Clone
      // KHÔNG do React quản → replaceWith an toàn. Index-aligned với node.querySelectorAll('img').
      onclone: (clonedDoc, clonedNode) => {
        try {
          const root = clonedNode && clonedNode.querySelectorAll ? clonedNode : clonedDoc
          const cimgs = Array.from(root.querySelectorAll('img'))
          cimgs.forEach((cim, i) => {
            const bmp = bitmaps[i]
            if (!bmp) return
            const c = clonedDoc.createElement('canvas')
            c.width = bmp.width // backing = độ phân giải gốc → nét
            c.height = bmp.height
            const cctx = c.getContext('2d')
            cctx.drawImage(bmp, 0, 0)
            _logoToBW(c, cctx) // ⭐ chuyển ĐEN-TRẮNG trước khi in (in nhiệt chỉ in đen)
            const sz = sizes[i]
            if (sz && sz.w) {
              c.style.width = sz.w + 'px' // hiển thị đúng cỡ layout của <img>
              c.style.height = sz.h + 'px'
            }
            c.style.display = 'block'
            if (cim.className) c.className = cim.className
            cim.replaceWith(c)
          })
        } catch {
          /* noop — lỗi thay logo thì bỏ logo, bill vẫn ra */
        }
      },
    })
  } finally {
    bitmaps.forEach((b) => {
      try {
        if (b && b.close) b.close() // giải phóng ImageBitmap
      } catch {
        /* noop */
      }
    })
  }
}

// Chụp node (hẹp hơn vùng in) rồi VẼ CANH GIỮA lên canvas đích rộng canvasWidth (= vùng in máy) →
// chừa LỀ ĐỆM trắng đều 2 bên (đệm dung sai: giấy xê dịch nhẹ vẫn không cắt/không lộ lệch).
// dx = (canvasWidth − billWidth)/2. canvasWidth ≤ bill → trả nguyên (không phình/cắt).
export async function captureNodeCentered(node, { scale = 1, canvasWidth } = {}) {
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
  return { dataUrl: canvas.toDataURL('image/png'), width: canvas.width, height: canvas.height, billWidth: bill.width, dx }
}
