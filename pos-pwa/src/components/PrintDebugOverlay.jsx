import { useEffect, useState } from 'react'
import { DEBUG_PRINT_BUILD, getPrintDebugLog, usePrintMode } from '../lib/printQueue'

// ⚠️⚠️ DEBUG TẠM — XÓA SAU (cùng _dbg/getPrintDebugLog/DEBUG_PRINT_BUILD ở printQueue.js).
// Overlay góc trái-dưới: printMode hiện tại + mảnh nào ĐANG mount (.print-receipt = bill /
// .print-lien2 = nhãn) + log lúc setMode/print(). Để founder bấm "In bill" / "In liên 2" rồi
// NHÌN overlay → thấy mode thật + mảnh thật (không đoán từ tờ in). Build marker [DBG-sync2]
// xác nhận đang chạy bundle MỚI (nếu marker không hiện / khác → PWA đang cache bundle CŨ →
// đóng hẳn app, mở lại / xoá cache). Overlay nằm trong #root → @media print ẩn (không in ra).
export default function PrintDebugOverlay() {
  const mode = usePrintMode()
  const [snap, setSnap] = useState({ bill: false, lien2: false })
  useEffect(() => {
    const t = setInterval(() => {
      setSnap({
        bill: !!document.querySelector('.print-receipt'),
        lien2: !!document.querySelector('.print-lien2'),
      })
    }, 200)
    return () => clearInterval(t)
  }, [])
  const log = getPrintDebugLog()
  return (
    <div style={{
      position: 'fixed', left: 4, bottom: 4, zIndex: 99999,
      background: '#000', color: '#0f0', font: '11px/1.35 monospace',
      padding: '4px 7px', borderRadius: 4, maxWidth: '78vw', opacity: 0.92,
    }}>
      <div>[{DEBUG_PRINT_BUILD}] mode=<b>{String(mode)}</b> · bill={snap.bill ? 'Y' : 'N'} · lien2={snap.lien2 ? 'Y' : 'N'}</div>
      {log.slice(-5).map((e, i) => (
        <div key={i}>{e.at}: mode={String(e.mode)} bill={e.bill ? 'Y' : 'N'} lien2={e.lien2 ? 'Y' : 'N'}</div>
      ))}
    </div>
  )
}
