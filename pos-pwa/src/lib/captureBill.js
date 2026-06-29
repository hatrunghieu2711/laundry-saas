import { dbg } from './debugLog' // ⚠️ TẠM — log convert logo

// ⚠️ TẠM (GĐ3) — chụp node bill → ảnh PNG để in printBitmap / kiểm layout.
// DÙNG DYNAMIC IMPORT html2canvas → KHÔNG vào bundle chính (chỉ tải khi bấm CHỤP/IN). Node phải
// HIỂN THỊ THẬT (off-screen left:-9999px), KHÔNG display:none.

// Chờ TẤT CẢ <img> trong node load + giải mã xong rồi mới chụp (tránh mất logo: <img src=logo_url>
// tải async, html2canvas chụp trước khi ảnh về → mất logo). Logo same-origin (/uploads/...) nên
// useCORS đủ. Ảnh lỗi/chậm → timeout (3s) vẫn chụp (KHÔNG treo việc in).
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
        im.decode().then(one, one) // chờ TẢI + GIẢI MÃ; lỗi cũng tính là xong
      } else {
        im.addEventListener('load', one, { once: true })
        im.addEventListener('error', one, { once: true })
      }
    })
    setTimeout(finish, timeoutMs) // chốt: ảnh chậm/lỗi vẫn chụp, không kẹt
  })
}

// ⭐ Đổi <img src=http(s)> → DATA-URI TRƯỚC khi chụp. html2canvas trong WebView APK TAINT ảnh http
// dù same-origin + useCORS (đã chứng minh: ảnh load OK nat=200x207 nhưng KHÔNG vẽ vào canvas). data-
// URI KHÔNG có cross-origin → vẽ CHẮC CHẮN. fetch→blob→readAsDataURL (logo /uploads/ same-origin →
// fetch được). Lỗi/timeout (3s) → giữ nguyên + log, KHÔNG treo việc in.
// TRẢ VỀ mảng dataUris[i] (index-aligned với node.querySelectorAll('img')) → onclone của html2canvas
// gán vào ảnh tương ứng trong BẢN CLONE (html2canvas render clone trong iframe ẩn, KHÔNG dùng node
// gốc → sửa src node gốc không chắc theo vào clone trên WebView APK).
async function _inlineImages(node, timeoutMs = 3000) {
  if (!node || typeof node.querySelectorAll !== 'function') {
    dbg('inline: node invalid')
    return []
  }
  const all = Array.from(node.querySelectorAll('img'))
  const dataUris = new Array(all.length).fill(null)
  const targets = all.map((im, i) => ({ im, i })).filter(({ im }) => /^https?:/i.test(im.src || ''))
  dbg(`inline: tim thay ${targets.length} img http (tong ${all.length})`) // ⚠️ TẠM — TRƯỚC early-return
  if (!targets.length) return dataUris
  const convert = async ({ im, i }) => {
    try {
      dbg(`inline img${i}: fetch ${(im.src || '').slice(0, 55)}`)
      const resp = await fetch(im.src, { cache: 'force-cache' })
      if (!resp.ok) throw new Error('HTTP ' + resp.status)
      const blob = await resp.blob()
      const dataUri = await new Promise((res, rej) => {
        const fr = new FileReader()
        fr.onload = () => res(fr.result)
        fr.onerror = () => rej(fr.error || new Error('FileReader'))
        fr.readAsDataURL(blob)
      })
      dataUris[i] = dataUri
      im.src = dataUri // node gốc (không hại; điểm MẤU CHỐT là onclone gán vào clone)
      if (typeof im.decode === 'function') await im.decode().catch(() => {})
      dbg(`inline img${i} OK len=${dataUri.length}`)
    } catch (e) {
      dbg(`inline img${i} LOI: ${e && e.message ? e.message : String(e)}`)
    }
  }
  // chờ convert hết NHƯNG có timeout chung → ảnh chậm/lỗi vẫn chụp (không treo)
  await Promise.race([
    Promise.all(targets.map((t) => convert(t))),
    new Promise((res) => setTimeout(res, timeoutMs)),
  ])
  return dataUris
}

async function _renderNode(node, scale) {
  const dataUris = await _inlineImages(node) // map index→dataURI (cho onclone)
  await _waitImages(node) // chờ mọi img sẵn sàng rồi mới chụp
  const html2canvas = (await import('html2canvas')).default
  return html2canvas(node, {
    backgroundColor: '#fff', // tránh nền trong suốt → đen khi in bitmap
    scale, // 1 = đúng px CSS; >1 → raster nét hơn
    useCORS: true,
    imageTimeout: 4000,
    logging: false,
    // ⭐ html2canvas render BẢN CLONE (iframe ẩn) → GÁN data-URI vào ảnh CLONE TẠI ĐÂY (sửa node
    // gốc không chắc theo vào clone trên WebView). Index-aligned với node.querySelectorAll('img').
    onclone: (clonedDoc, clonedNode) => {
      try {
        const root = clonedNode && clonedNode.querySelectorAll ? clonedNode : clonedDoc
        const cimgs = Array.from(root.querySelectorAll('img'))
        let n = 0
        cimgs.forEach((im, i) => {
          if (dataUris && dataUris[i]) {
            im.src = dataUris[i]
            im.removeAttribute('crossorigin')
            n += 1
          }
        })
        dbg(`onclone: set ${n} img -> dataURI (clone imgs=${cimgs.length})`)
      } catch (e) {
        dbg('onclone loi: ' + (e && e.message ? e.message : String(e)))
      }
    },
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
