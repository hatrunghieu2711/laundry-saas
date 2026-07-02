import { useCallback, useEffect, useRef, useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { useBranch } from '../context/BranchContext'
import { useShift } from '../context/ShiftContext'
import Receipt from '../components/Receipt'
import MoneyInput from '../components/MoneyInput'
import ShiftEmpty from '../components/ShiftEmpty'
import { Lien2PrintLayer } from '../components/Lien2Label'
import Lien2PrintButton from '../components/Lien2PrintButton'
import { usePrintQueue } from '../lib/printQueue'
import { ApiError, api } from '../lib/api'
import { formatDateTime, formatVND, toNumber } from '../lib/format'
import {
  QUARTERS,
  addDaysVn,
  combineVn,
  dateInputValueVn,
  defaultPickupVnWall,
  formatPickupLong,
  getVnHour,
  getVnMinute,
  isPastVnWall,
  isSameDayVn,
  nearestQuarterIndex,
  parseDateInputVn,
  startOfDayVn,
  vnWallToISO,
} from '../lib/datetime'

const HOURS = Array.from({ length: 24 }, (_, h) => h)
import { PAYMENT_METHOD } from '../lib/orders'
import { normalizeService } from '../lib/services'
import { getReceiptConfig } from '../lib/receipt'
import ServicePicker from '../components/ServicePicker'

const PREPAY_METHODS = ['cash', 'transfer', 'qr']

// Màn tạo đơn (Stage 3.8): layout 3 vùng KHÔNG cuộn toàn trang
// (tab danh mục | lưới dịch vụ | giỏ). Bấm TẠO ĐƠN → modal xác nhận
// (SĐT/tên khách + wheel giờ giao) rồi mới tạo.
export default function OrderNew() {
  const { user } = useAuth()
  const navigate = useNavigate()
  const isOwner = user?.role === 'owner'
  const canManage = user?.role === 'owner' || user?.role === 'manager'
  // Gói HẾT HẠN (quá ân hạn) → chặn TẠO đơn (BE đã 403; FE ngăn trước cho UX).
  // grace/warning vẫn tạo được. Banner toàn app ở Layout.
  const subExpired = user?.subscription_status === 'expired'

  // Chi nhánh chọn từ HEADER (Stage 6.6.1) — dropdown ở header, không còn hàng riêng.
  const { branchId } = useBranch()
  const { setShiftOpen } = useShift() // nhãn tab "Ca" động (6.71): mở ca tại đây → set đang-mở
  const [shiftState, setShiftState] = useState('loading') // loading|open|none|needbranch
  const [opening, setOpening] = useState('')      // tiền đầu ca — mở ca ngay tại màn tạo đơn (6.54)
  const [openSug, setOpenSug] = useState(0)
  const [openHasPrev, setOpenHasPrev] = useState(false) // có ca trước → đối chiếu (6.55)
  const [openReason, setOpenReason] = useState('')
  const [openReasonErr, setOpenReasonErr] = useState(false)
  const [openBusy, setOpenBusy] = useState(false)
  const [services, setServices] = useState([])
  const [svcLoading, setSvcLoading] = useState(true)
  const [cart, setCart] = useState([])
  const [pickerReset, setPickerReset] = useState(0) // bump sau khi tạo đơn → ServicePicker reset search+kg (giữ tab)
  const [turnaround, setTurnaround] = useState(4) // từ tenant settings
  // null = chưa biết (đang nạp settings) · true = tự in · false = không tự in.
  const [autoPrint, setAutoPrint] = useState(null)        // BILL
  const [autoPrintCopy2, setAutoPrintCopy2] = useState(null) // LIÊN 2 — TÁCH RIÊNG
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [created, setCreated] = useState(null)
  const [printed, setPrinted] = useState(false) // đã gọi window.print() cho đơn này
  // Cấu hình bill nạp SẴN (cùng nguồn với In thủ công) để auto-print dùng ĐÚNG mẫu
  // tenant ngay từ render đầu, không rơi vào DEFAULT_RECEIPT (Stage 6.8.1).
  const [receiptConfig, setReceiptConfig] = useState(null)
  const [logoReady, setLogoReady] = useState(false)
  const idRef = useRef(0)
  const printedRef = useRef(null) // mã đơn đã auto-in (in 1 lần/đơn) — Stage 6.8

  // ── modal xác nhận (wizard 2 bước — Stage 6.7) ──
  const [showConfirm, setShowConfirm] = useState(false)
  // confirmActive: phiên xác nhận ĐANG mở (đã nhập liệu) — đóng modal để "Thêm dịch
  // vụ" KHÔNG reset; mở lại = resume giữ nguyên thông tin (Stage 6.8).
  const [confirmActive, setConfirmActive] = useState(false)
  const [step, setStep] = useState(1) // 1 = khách & giờ giao · 2 = thanh toán
  const [adjOpen, setAdjOpen] = useState(false) // phụ thu/giảm ẩn sau "Thêm" (bước 2)
  const [phone, setPhone] = useState('')
  const [custName, setCustName] = useState('')
  const [custFound, setCustFound] = useState(null)
  const [custSug, setCustSug] = useState([])   // gợi ý autocomplete khách (6.49)
  const [sugOpen, setSugOpen] = useState(false)
  const [note, setNote] = useState('')
  const [pickup, setPickup] = useState(() => defaultPickupVnWall(3))
  // ── bước thanh toán trong modal ──
  const [payMode, setPayMode] = useState('prepay') // prepay | later (2H: thu ĐỦ hoặc chưa thu)
  const [payMethod, setPayMethod] = useState('cash')
  const [paidInfo, setPaidInfo] = useState({ amount: 0, method: null })
  const [payWarn, setPayWarn] = useState('')
  // ── phụ thu / giảm giá (Stage 5.4) — gộp 2 tab, mặc định Giảm giá (6.6.3) ──
  const [adjTab, setAdjTab] = useState('discount') // discount | surcharge
  const [surType, setSurType] = useState('percent')
  const [surValue, setSurValue] = useState('')
  const [surReason, setSurReason] = useState('')
  const [surAuto, setSurAuto] = useState(false)
  const [disType, setDisType] = useState('percent')
  const [disValue, setDisValue] = useState('')
  const [disReason, setDisReason] = useState('')
  const [disAuto, setDisAuto] = useState(false)

  // Chi nhánh hiệu lực để LỌC dịch vụ ẩn: owner → CN chọn ở header; nhân viên → CN của mình.
  // Có CN → /services?branch_id= (loại dịch vụ ẩn ở CN đó); chưa có → trả hết. Reload khi đổi CN.
  const effBranch = isOwner ? branchId : user?.branch_id
  useEffect(() => {
    setSvcLoading(true)
    api
      .get(`/services?limit=200${effBranch ? `&branch_id=${effBranch}` : ''}`)
      .then((p) => setServices(p.items.map(normalizeService)))
      .catch(() => setServices([]))
      .finally(() => setSvcLoading(false))
  }, [effBranch])

  // Turnaround + cờ tự-in từ tenant settings. Lỗi → turnaround 4, tự-in mặc định BẬT.
  useEffect(() => {
    api
      .get('/settings/pos')
      .then((s) => {
        setTurnaround(s.default_turnaround_hours ?? 4)
        setAutoPrint(s.auto_print_receipt !== false) // default true
        setAutoPrintCopy2(s.auto_print_copy2 !== false) // default true
      })
      .catch(() => { setAutoPrint(true); setAutoPrintCopy2(true) })
  }, [])

  // Nạp SẴN cấu hình bill + preload logo (Stage 6.8.1) → auto-print in ĐÚNG mẫu
  // tenant ngay, không in nhầm mẫu mặc định.
  useEffect(() => {
    let alive = true
    const safety = setTimeout(() => alive && setLogoReady(true), 2500) // logo lỗi/chậm → vẫn in
    getReceiptConfig().then((cfg) => {
      if (!alive) return
      setReceiptConfig(cfg)
      if (cfg.logo_url) {
        const img = new Image()
        img.onload = img.onerror = () => alive && setLogoReady(true)
        img.src = cfg.logo_url
      } else {
        setLogoReady(true)
      }
    })
    return () => {
      alive = false
      clearTimeout(safety)
    }
  }, [])
  const printReady = receiptConfig !== null && logoReady
  // Hàng đợi in tuần tự (Stage 6.9.4): bill + liên 2 = các job RIÊNG → máy cắt rời.
  const { active: printJob, printing: printingQueue, run: runPrint } = usePrintQueue()

  const checkShift = useCallback(async () => {
    setError('')
    if (isOwner && !branchId) {
      setShiftState('needbranch')
      return
    }
    setShiftState('loading')
    try {
      const q = isOwner ? `?branch_id=${branchId}` : ''
      await api.get(`/shifts/current${q}`)
      setShiftState('open')
    } catch (err) {
      setShiftState('none')
      if (!(err instanceof ApiError && err.status === 404)) setError(err?.message || '')
    }
  }, [isOwner, branchId])

  useEffect(() => {
    checkShift()
  }, [checkShift])

  // Chưa có ca → lấy gợi ý tiền đầu ca (= tiền để lại ca trước) để điền sẵn form mở ca tại đây.
  useEffect(() => {
    if (shiftState !== 'none') return undefined
    let alive = true
    const q = isOwner && branchId ? `?branch_id=${branchId}` : ''
    api.get(`/shifts/opening-suggestion${q}`)
      .then((s) => {
        if (!alive) return
        const sug = toNumber(s.suggested_opening_cash)
        setOpenSug(sug)
        setOpenHasPrev(!!s.has_previous)
        setOpening(sug > 0 ? String(sug) : '')
      })
      .catch(() => {})
    return () => { alive = false }
  }, [shiftState, isOwner, branchId])

  // Mở ca NGAY tại màn tạo đơn (6.54) — cùng API tab Ca (POST /shifts/open, cần tiền đầu ca).
  // 6.55: lệch tiền để lại ca trước → BẮT lý do (đai an toàn FE; backend cũng enforce 422).
  // Mở xong checkShift() → shiftState='open' → vào thẳng màn tạo đơn.
  const openShiftHere = async () => {
    const openDiff = openHasPrev && toNumber(opening) !== openSug
    if (openDiff && !openReason.trim()) {
      setOpenReasonErr(true)
      return
    }
    setOpenBusy(true)
    setError('')
    setOpenReasonErr(false)
    try {
      const body = { opening_cash: toNumber(opening) }
      if (isOwner) body.branch_id = branchId
      if (openDiff) body.opening_diff_reason = openReason.trim()
      await api.post('/shifts/open', body)
      setShiftOpen(true) // 6.71: ca vừa mở → nhãn tab đổi "Mở ca" → "Đóng ca"
      await checkShift()
    } catch (err) {
      if (err instanceof ApiError && err.code === 'OPENING_DIFF_REASON_REQUIRED') {
        setOpenReasonErr(true)
      } else {
        setError(err instanceof ApiError && err.code === 'SHIFT_ALREADY_OPEN'
          ? 'Chi nhánh đang có ca mở.' : (err?.message || 'Không mở được ca'))
      }
    } finally {
      setOpenBusy(false)
    }
  }

  // ── giỏ ──
  const newId = () => {
    idRef.current += 1
    return idRef.current
  }
  // ServicePicker phát onPick(payload) → dựng dòng giỏ y HỆT addPerUnit/addFlat/addOverflow cũ
  // (dựng từ payload.service/tier, KHÔNG từ label/quantity → shape giỏ + body POST /orders bất biến).
  const handlePick = (p) => {
    if (p.kind === 'per_unit') {
      const svc = p.service
      setCart((prev) => {
        const i = prev.findIndex((x) => x.kind === 'per_unit' && x.service_id === svc.id)
        if (i >= 0) {
          const n = [...prev]
          n[i] = { ...n[i], quantity: n[i].quantity + 1 }
          return n
        }
        return [
          ...prev,
          { id: newId(), kind: 'per_unit', service_id: svc.id, name: svc.name,
            unit: svc.unit, unit_price: svc.unit_price, quantity: 1 },
        ]
      })
    } else if (p.kind === 'flat') {
      const svc = p.service
      const tier = p.tier
      setCart((prev) => {
        const i = prev.findIndex((x) => x.kind === 'flat' && x.tier_id === tier.id)
        if (i >= 0) {
          const n = [...prev]
          n[i] = { ...n[i], count: n[i].count + 1 }
          return n
        }
        return [
          ...prev,
          { id: newId(), kind: 'flat', service_id: svc.id, tier_id: tier.id,
            name: `${svc.name} (${tier.label})`, price: tier.price,
            weight: tier.max_value ?? 0, count: 1 },
        ]
      })
    } else if (p.kind === 'overflow') {
      const svc = p.service
      const tier = p.tier
      const kg = p.quantity // đã > 0 (ServicePicker chặn kg<=0 trước khi emit)
      setCart((prev) => [
        ...prev,
        { id: newId(), kind: 'overflow', service_id: svc.id,
          name: `${svc.name} (${tier.label})`, unit_price: tier.price, quantity: kg },
      ])
    }
  }
  const bump = (id, delta) =>
    setCart((prev) =>
      prev
        .map((x) => {
          if (x.id !== id) return x
          if (x.kind === 'flat') return { ...x, count: x.count + delta }
          return { ...x, quantity: x.quantity + delta }
        })
        .filter((x) => (x.kind === 'flat' ? x.count > 0 : x.quantity > 0)),
    )
  const removeItem = (id) => setCart((prev) => prev.filter((x) => x.id !== id))
  const lineTotal = (x) => (x.kind === 'flat' ? x.count * x.price : x.quantity * x.unit_price)
  const total = cart.reduce((s, x) => s + lineTotal(x), 0)

  // ── breakdown phụ thu / giảm (Stage 5.4): % tính trên tổng món (total) ──
  const _adj = (type, value) => {
    const v = toNumber(value)
    if (v <= 0) return 0
    return type === 'percent' ? Math.round((total * v) / 100) : Math.round(v)
  }
  const surAmount = _adj(surType, surValue)
  const disAmount = Math.min(_adj(disType, disValue), total + surAmount) // không âm
  const grandTotal = total + surAmount - disAmount

  const buildItems = () => {
    const items = []
    for (const x of cart) {
      if (x.kind === 'flat') {
        for (let k = 0; k < x.count; k += 1) items.push({ service_id: x.service_id, quantity: x.weight })
      } else {
        items.push({ service_id: x.service_id, quantity: x.quantity })
      }
    }
    return items
  }

  // Bộ chọn dịch vụ (tab/lưới/tìm) đã tách ra <ServicePicker> — state tab/search/overflowKg +
  // tabs/shown + auto-select tab nằm trong component đó; OrderNew chỉ nhận onPick → handlePick.

  // ── modal ──
  // "Thêm dịch vụ": đóng modal về màn chọn, GIỮ NGUYÊN mọi thông tin (Stage 6.8).
  const addMoreServices = () => {
    setShowConfirm(false)
    setError('')
  }

  // Hủy/thoát luồng tạo đơn (Stage 6.53): đơn CHƯA vào DB trước nút "Tạo đơn" cuối →
  // chỉ điều hướng đi (unmount xóa state nháp), KHÔNG gọi API. Có nhập gì → hỏi xác nhận.
  const cancelDraft = () => {
    const hasDraft = cart.length > 0 || phone.trim() || custName.trim() || note.trim()
    if (hasDraft && !window.confirm('Hủy đơn đang tạo? Thông tin chưa lưu sẽ mất.')) return
    navigate('/board')
  }

  const openConfirm = async () => {
    if (cart.length === 0) return
    // Đang có phiên (vừa "Thêm dịch vụ") → MỞ LẠI, giữ nguyên thông tin đã nhập;
    // tổng tiền tự tính lại theo giỏ hiện tại (có món mới). KHÔNG reset/áp lại rule.
    if (confirmActive) {
      setError('')
      setShowConfirm(true)
      return
    }
    setConfirmActive(true)
    // Giờ hẹn MẶC ĐỊNH = hiện tại + 3 giờ (Stage 6.49, làm tròn lên 15'; theo giờ VN) —
    // nhân viên sửa được. (Trước 6.49 mặc định 08:00.)
    setPickup(defaultPickupVnWall(3))
    setStep(1)
    setAdjOpen(false)
    setPayMode('prepay')
    setPayMethod('cash')
    setError('')
    // reset phụ thu/giảm
    setSurType('percent'); setSurValue(''); setSurReason(''); setSurAuto(false)
    setDisType('percent'); setDisValue(''); setDisReason(''); setDisAuto(false)
    setShowConfirm(true)
    // Lấy rule tự áp hôm nay → điền sẵn (badge "tự áp"), nhân viên sửa được.
    try {
      const appl = await api.get('/price-rules/applicable')
      if (appl?.surcharge) {
        setSurType(appl.surcharge.value_type)
        setSurValue(String(toNumber(appl.surcharge.value)))
        setSurReason(appl.surcharge.name || '')
        setSurAuto(true)
      }
      if (appl?.discount) {
        setDisType(appl.discount.value_type)
        setDisValue(String(toNumber(appl.discount.value)))
        setDisReason(appl.discount.name || '')
        setDisAuto(true)
      }
    } catch {
      /* không có rule / lỗi mạng → tạo đơn không phụ thu-giảm tự áp */
    }
  }

  // Gợi ý khách theo SĐT/tên (debounce) khi modal mở — autocomplete (6.49).
  useEffect(() => {
    if (!showConfirm) return undefined
    const ph = phone.trim()
    if (ph.length < 3) {
      setCustFound(null)
      setCustSug([])
      return undefined
    }
    let alive = true
    const t = setTimeout(async () => {
      try {
        const res = await api.get(`/customers?q=${encodeURIComponent(ph)}&limit=8`)
        if (!alive) return
        const items = res.items || []
        setCustSug(items)
        // khớp SĐT chính xác → coi là "khách quen" (hint + link customer_id), điền tên.
        const exact = items.find((c) => c.phone === ph)
        if (exact) {
          setCustFound(exact)
          setCustName(exact.full_name || '')
        } else {
          setCustFound(null)
        }
      } catch {
        if (alive) { setCustFound(null); setCustSug([]) }
      }
    }, 400)
    return () => {
      alive = false
      clearTimeout(t)
    }
  }, [phone, showConfirm])

  // Chọn 1 gợi ý → điền SĐT + tên, link khách quen, đóng dropdown.
  const pickCust = (c) => {
    setPhone(c.phone || '')
    setCustName(c.full_name || '')
    setCustFound(c)
    setSugOpen(false)
  }

  // Bước 1 → 2: chặn giờ quá khứ trước khi sang bước thanh toán.
  const goStep2 = () => {
    if (isPastVnWall(pickup)) {
      setError('Không thể hẹn giờ giao trong quá khứ. Chọn lại giờ giao.')
      return
    }
    setError('')
    setStep(2)
  }

  const submit = async () => {
    if (cart.length === 0) return
    if (isPastVnWall(pickup)) {
      setError('Không thể hẹn giờ giao trong quá khứ. Chọn lại giờ giao.')
      return
    }
    setBusy(true)
    setError('')
    try {
      const ph = phone.trim()
      const nm = custName.trim()
      let customerId
      let overwriteName = null // gửi xuống BE để GHI ĐÈ tên (chỉ khi link customer đã có)
      if (ph) {
        // Có SĐT: tìm theo SĐT (như cũ) → thấy dùng id; không thấy → tạo mới.
        if (custFound) {
          customerId = custFound.id
          // Khách quen quay lại: tên nhập (KỂ CẢ rỗng) ghi đè tên cũ — SĐT có thể đổi chủ.
          overwriteName = nm
        } else {
          const c = await api.post('/customers', { phone: ph, full_name: nm || undefined })
          customerId = c.id
        }
      } else if (nm) {
        // CHỈ có TÊN, không SĐT: tạo customer chỉ-tên (phone để trống) → backend lưu
        // hợp lệ (customers.phone nullable) → gắn customer_id, KHÔNG mất tên đã nhập.
        const c = await api.post('/customers', { full_name: nm })
        customerId = c.id
      }
      // Không nhập cả SĐT lẫn tên → khách vãng lai (customer_id NULL) → "Khách lẻ".
      const body = { items: buildItems(), pickup_at: vnWallToISO(pickup) }
      if (customerId) body.customer_id = customerId
      if (overwriteName !== null) body.customer_name = overwriteName // "" = ghi đè rỗng
      if (note.trim()) body.notes = note.trim()
      if (isOwner) body.branch_id = branchId
      // Phụ thu/giảm: gửi giá trị ĐANG HIỂN THỊ (đã gồm rule điền sẵn + sửa tay)
      // → backend dùng đúng số này (không tự áp lại). value 0 = không áp.
      body.surcharge = { value_type: surType, value: toNumber(surValue) }
      if (surReason.trim()) body.surcharge.reason = surReason.trim()
      body.discount = { value_type: disType, value: toNumber(disValue) }
      if (disReason.trim()) body.discount.reason = disReason.trim()
      // Thu trước = thu ĐỦ 100% (2H không có thu một phần). Server tự ghi full =
      // total_amount; KHÔNG gửi số tiền tùy ý. Thu sau = chưa thu gì lúc tạo.
      if (payMode === 'prepay') {
        body.prepay = true
        body.payment_method = payMethod
      }
      const order = await api.post('/orders', body)

      const paid =
        payMode === 'prepay'
          ? { amount: toNumber(order.total_amount), method: payMethod }
          : { amount: 0, method: null }
      setPaidInfo(paid)
      setPayWarn('')
      setShowConfirm(false)
      setConfirmActive(false)
      setCreated(order)
    } catch (err) {
      if (err instanceof ApiError && err.code === 'NO_OPEN_SHIFT') {
        setError('Chi nhánh chưa có ca mở.')
      } else if (err instanceof ApiError && err.code === 'PICKUP_AT_IN_PAST') {
        setError('Không thể hẹn giờ giao trong quá khứ. Chọn lại giờ giao.')
      } else {
        setError(err?.message || 'Không tạo được đơn, thử lại.')
      }
    } finally {
      setBusy(false)
    }
  }

  const startNew = () => {
    setCreated(null)
    setPrinted(false)
    setConfirmActive(false)
    setCart([])
    setPhone('')
    setCustName('')
    setCustFound(null)
    setCustSug([])
    setSugOpen(false)
    setNote('')
    setPickerReset((n) => n + 1) // ServicePicker tự xóa search + overflowKg (GIỮ tab đang chọn)
    setError('')
    setPaidInfo({ amount: 0, method: null })
    setPayWarn('')
  }

  // Tạo đơn xong (auto_print BẬT) → in TUẦN TỰ: BILL rồi LIÊN 2 (1 nhãn không số) → máy Sunmi
  // cắt rời 2 tờ (Stage 6.9.4). In 1 lần/đơn (printedRef). CHỜ printReady (config+logo) → in
  // đúng mẫu tenant (6.8.1). Xong → printed=true (hiện màn tóm tắt; dùng nút In lại/In liên 2).
  useEffect(() => {
    if (!created || !printReady) return
    if (autoPrint === null || autoPrintCopy2 === null) return // chờ nạp settings
    // TÁCH RIÊNG: bill / liên 2 độc lập → in bill-only / liên2-only / cả hai / không gì.
    // 3d-2: kèm order/config → NATIVE chụp đúng đơn vừa tạo (web bỏ qua → T1 không đổi). created +
    // receiptConfig CHẮC CHẮN sẵn ở đây (guard !created/!printReady; printReady = config!=null & logo).
    const jobs = []
    if (autoPrint) jobs.push({ mode: 'bill', order: created, config: receiptConfig })
    if (autoPrintCopy2) jobs.push({ mode: 'lien2', seq: null, order: created, lien2Cfg: receiptConfig?.lien2 })
    if (!jobs.length) return // cả hai tắt → KHÔNG tự in (nhân viên in tay)
    if (printedRef.current === created.id) return
    printedRef.current = created.id
    runPrint(jobs, () => setPrinted(true))
  }, [created, autoPrint, autoPrintCopy2, printReady, runPrint])

  // ── sau khi tạo đơn: render Bill (portal) NGAY + in thẳng (đúng mẫu tenant).
  //    Trước khi in chỉ hiện 1 dòng "đang chuẩn bị/in" (calm) — KHÔNG nháy lưới
  //    an toàn. Sau khi đã gọi in (printed) mới hiện nút (dự phòng nếu máy không
  //    bắn 'afterprint'). Mã đơn nằm trên bill. Stage 6.8.1. ──
  if (created) {
    // Đang chạy hàng đợi in (hoặc auto_print BẬT chưa in xong) → màn chờ calm,
    // KHÔNG nháy lưới an toàn. Xong / auto_print TẮT → màn tóm tắt.
    const noAutoPrint = autoPrint === false && autoPrintCopy2 === false // cả hai tắt
    const showSummary = !printingQueue && (printed || noAutoPrint)
    // Nút "In bill" THỦ CÔNG = CHỈ bill (nhãn liên 2 in qua nút "In liên 2" riêng). Trước
    // đây in cả bill+lien2 gây hiểu nhầm "In bill → ra nhãn". (Auto-print khi tạo đơn vẫn
    // theo cài đặt auto_print_receipt/auto_print_copy2 — KHÔNG đổi.)
    // 3d-1: kèm order+config → in NATIVE (printBitmap) khi nativePrintActive(); web bỏ qua 2 field
    // này (window.print render portal như cũ) → T1 KHÔNG đổi.
    const printBill = () => runPrint([{ mode: 'bill', order: created, config: receiptConfig }])
    return (
      <div className="ordernew">
        {!showSummary ? (
          <div className="ordok ordok--wait">
            <p className="shift__hint">{printingQueue ? 'Đang in phiếu…' : 'Đang chuẩn bị phiếu in…'}</p>
          </div>
        ) : (
          <div className="ordok">
            <div className="ordok__head"><span className="ordok__check"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg></span> Đã tạo đơn</div>
            <div className="ordok__code">
              <span className="ordok__code-lbl">Mã đơn hàng</span>
              <span className="ordok__code-val">{created.order_code}</span>
            </div>
            <div className="ordok__rows">
              <div className="ordok__row"><span>Tên khách</span><strong>{created.customer_name || 'Khách vãng lai'}</strong></div>
              <div className="ordok__row ordok__row--sec"><span>SĐT</span><span>{created.customer_phone || '—'}</span></div>
              <div className="ordok__row ordok__row--sec"><span>Giờ nhận</span><span>{formatDateTime(created.created_at)}</span></div>
              <div className="ordok__row"><span>Giờ giao</span><strong>{formatDateTime(created.pickup_at)}</strong></div>
            </div>
            {payWarn && <div className="alert alert--error">{payWarn}</div>}
            <div className="ordok__actions">
              <div className="ordok__actrow">
                <button className="btn btn--ghost" onClick={printBill}>
                  {printed ? 'In lại bill' : 'In bill'}
                </button>
                <Lien2PrintButton order={created} className="btn btn--ghost" />
              </div>
              <div className="ordok__actrow">
                <button className="btn btn--primary" onClick={startNew}>Tạo đơn mới</button>
                <button className="btn btn--ghost" onClick={() => navigate('/board')}>Đơn hàng</button>
              </div>
            </div>
            <p className="ordok__hint">
              {noAutoPrint
                ? 'Bấm In bill / In liên 2 nếu cần.'
                : 'Đã in theo cài đặt. In lại nếu cần, hoặc Tạo đơn mới.'}
            </p>
          </div>
        )}
        <Receipt config={receiptConfig} order={created} paid={paidInfo.amount} method={paidInfo.method} />
        {/* LIÊN 2: chỉ render khi job liên 2 đang in (auto kèm bill / In lại) — 1 nhãn/lần. */}
        {printJob?.mode === 'lien2' && <Lien2PrintLayer order={created} seq={printJob.seq} cfg={receiptConfig?.lien2} />}
      </div>
    )
  }

  if (shiftState === 'loading') return <p className="shift__hint">Đang kiểm tra ca…</p>

  if (shiftState === 'needbranch') {
    return (
      <div className="ordernew">
        <p className="shift__hint">Chọn chi nhánh ở thanh trên để tạo đơn.</p>
      </div>
    )
  }
  if (shiftState === 'none') {
    return (
      <div className="ordernew">
        <ShiftEmpty>
          <p>Cần mở ca trước khi tạo đơn.</p>
          <div className="on-open">
            <label className="field">
              <span>Tiền đầu ca{openSug > 0 ? ` (gợi ý ${formatVND(openSug)})` : ''}</span>
              <MoneyInput value={opening} onChange={setOpening} />
            </label>
            {openHasPrev && opening !== '' && toNumber(opening) !== openSug && (
              <>
                <p className="shift__warn">
                  Lệch {formatVND(toNumber(opening) - openSug)} so với tiền để lại ca trước ({formatVND(openSug)}). Đếm lại trước khi xác nhận.
                </p>
                <label className="field">
                  <span>Lý do lệch (bắt buộc)</span>
                  <input
                    className="input"
                    value={openReason}
                    onChange={(e) => { setOpenReason(e.target.value); setOpenReasonErr(false) }}
                    placeholder="VD: bù quỹ đầu ca / thiếu chưa rõ…"
                  />
                  {openReasonErr && <span className="field-note field-note--err">Bắt buộc nhập lý do khi tiền đầu ca lệch.</span>}
                </label>
              </>
            )}
            {error && <div className="alert alert--error">{error}</div>}
            <button className="btn btn--primary btn--xl btn--block" onClick={openShiftHere} disabled={openBusy}>
              {openBusy ? 'Đang mở ca…' : 'MỞ CA'}
            </button>
            <button className="btn btn--ghost btn--block" onClick={() => navigate('/')} disabled={openBusy}>
              Tới màn Ca
            </button>
          </div>
        </ShiftEmpty>
      </div>
    )
  }

  // ── builder 3 vùng ──

  // ── Giờ hẹn giao: dropdown ngày/giờ/phút (thay wheel — gọn, hợp Chrome cũ) ──
  const pkDay = startOfDayVn(pickup)
  const pkHour = getVnHour(pickup)
  const pkMinIdx = nearestQuarterIndex(getVnMinute(pickup))
  const vnNowDay = startOfDayVn(new Date(Date.now() + 7 * 60 * 60 * 1000))
  const isToday = isSameDayVn(pkDay, vnNowDay)
  const isTomorrow = isSameDayVn(pkDay, addDaysVn(vnNowDay, 1))
  const setPickDay = (d) => setPickup(combineVn(d, pkHour, QUARTERS[pkMinIdx]))
  const pickupPast = isPastVnWall(pickup)

  return (
    <div className="ordernew ordernew--zones">
      {error && !showConfirm && <div className="alert alert--error">{error}</div>}

      <div className="zones">
        {/* Vùng trái + giữa: bộ chọn dịch vụ (tab danh mục + lưới + ô tìm) — component dùng chung. */}
        <ServicePicker
          services={services}
          loading={svcLoading}
          canManage={canManage}
          onManagePrices={() => navigate('/services')}
          onPick={handlePick}
          resetSignal={pickerReset}
        />

        {/* Vùng phải: giỏ + nút tạo đơn */}
        <aside className="zones__cart">
          <div className="zones__cart-list">
            {cart.length === 0 ? (
              <p className="cart__empty">Bấm dịch vụ để thêm vào đơn.</p>
            ) : (
              cart.map((x) => (
                <div className="cart__item" key={x.id}>
                  <div className="cart__top">
                    <span className="cart__name" title={x.name}>{x.name}</span>
                    <button className="cart__del" onClick={() => removeItem(x.id)} aria-label="Xóa">
                      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2.4" strokeLinecap="round" aria-hidden="true"><path d="M6 6l12 12 M6 18L18 6" /></svg>
                    </button>
                  </div>
                  <div className="cart__bot">
                    <div className="cart__qty">
                      <button className="qty-btn" onClick={() => bump(x.id, -1)}>
                        −
                      </button>
                      <span className="qty-val">{x.kind === 'flat' ? x.count : x.quantity}</span>
                      <button className="qty-btn" onClick={() => bump(x.id, +1)}>
                        ＋
                      </button>
                    </div>
                    <span className="cart__amt">{formatVND(lineTotal(x))}</span>
                  </div>
                </div>
              ))
            )}
          </div>
          <div className="zones__cart-foot">
            <div className="order-bar__total">
              <span>Tổng</span>
              <strong>{formatVND(total)}</strong>
            </div>
            <button
              className="btn btn--primary btn--lg"
              onClick={openConfirm}
              disabled={cart.length === 0}
            >
              TẠO ĐƠN
            </button>
          </div>
        </aside>
      </div>

      {/* Modal xác nhận đơn — 2 cột màn POS ngang, đường kẻ thẳng (Stage 6.6.3).
          TRÁI: khách + phụ thu/giảm · PHẢI: giờ giao + tổng + thanh toán. */}
      {showConfirm && (
        <div className="modal-overlay modal-overlay--top" role="dialog" aria-modal="true">
          <div className="modal cfm">
            <div className="cfm__head">
              <span className="cfm__title">Xác nhận đơn</span>
              <span className="cfm__spacer" />
              <span className="cfm__steps">
                <span className={`cfm__dot ${step === 1 ? 'cfm__dot--active' : 'cfm__dot--done'}`}>{step === 1 ? '1' : <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" aria-hidden="true"><path d="M20 6L9 17l-5-5" /></svg>}</span>
                <span className={`cfm__bar ${step === 2 ? 'cfm__bar--done' : ''}`} />
                <span className={`cfm__dot ${step === 2 ? 'cfm__dot--active' : ''}`}>2</span>
              </span>
              {/* Thoát luồng tạo đơn — góc trên, tách xa nút "Tạo đơn" (đáy) tránh bấm nhầm. */}
              <button type="button" className="cfm__cancel" onClick={cancelDraft} disabled={busy}>Hủy</button>
            </div>

            <div className="cfm__body">
              {step === 1 ? (
                /* BƯỚC 1 — Khách & giờ giao (có nhập liệu, ít trường) */
                <div className="cfm__cols">
                  <div className="cfm__col">
                    <div className="cust-ac">
                      <label className="field">
                        <span>SĐT khách (trống = vãng lai)</span>
                        <input className="input" type="tel" inputMode="numeric" placeholder="VD 0905..."
                          value={phone} onChange={(e) => { setPhone(e.target.value); setSugOpen(true) }} />
                      </label>
                      {sugOpen && custSug.length > 0 && (
                        <ul className="cust-ac__list">
                          {custSug.map((c) => (
                            <li key={c.id}>
                              <button type="button" className="cust-ac__item" onClick={() => pickCust(c)}>
                                <span className="cust-ac__name">{c.full_name || '(chưa có tên)'}</span>
                                <span className="cust-ac__phone">{c.phone || '—'}</span>
                              </button>
                            </li>
                          ))}
                        </ul>
                      )}
                    </div>
                    {phone.trim() && (
                      <p className={`cust-hint ${custFound ? 'cust-hint--known' : ''}`}>
                        {custFound ? `Khách quen: ${custFound.full_name || '(chưa có tên)'}` : 'Khách mới — nhập tên'}
                      </p>
                    )}
                    <label className="field">
                      <span>Tên khách</span>
                      <input className="input" type="text" placeholder="Tên khách (tùy chọn)"
                        value={custName} onChange={(e) => setCustName(e.target.value)} />
                    </label>
                    <label className="field">
                      <span>Ghi chú</span>
                      <input className="input" type="text" placeholder="VD: giặt riêng…"
                        value={note} onChange={(e) => setNote(e.target.value)} />
                    </label>
                  </div>

                  <div className="cfm__col cfm__col--right">
                    <span className="field-label">Giờ hẹn giao</span>
                    <div className="cfm__daybtns">
                      <button type="button" className={`chip chip--sm ${isToday ? 'chip--active' : ''}`} onClick={() => setPickDay(vnNowDay)}>Hôm nay</button>
                      <button type="button" className={`chip chip--sm ${isTomorrow ? 'chip--active' : ''}`} onClick={() => setPickDay(addDaysVn(vnNowDay, 1))}>Ngày mai</button>
                    </div>
                    <div className="cfm__timesel">
                      <input className="input" type="date" min={dateInputValueVn(vnNowDay)}
                        value={dateInputValueVn(pkDay)}
                        onChange={(e) => e.target.value && setPickDay(parseDateInputVn(e.target.value))} />
                      <select className="input" value={pkHour}
                        onChange={(e) => setPickup(combineVn(pickup, Number(e.target.value), QUARTERS[pkMinIdx]))}>
                        {HOURS.map((h) => <option key={h} value={h}>{String(h).padStart(2, '0')}</option>)}
                      </select>
                      <span className="cfm__colon">:</span>
                      <select className="input" value={pkMinIdx}
                        onChange={(e) => setPickup(combineVn(pickup, pkHour, QUARTERS[Number(e.target.value)]))}>
                        {QUARTERS.map((m, i) => <option key={m} value={i}>{String(m).padStart(2, '0')}</option>)}
                      </select>
                    </div>
                    <div className={`cfm__when-note ${pickupPast ? 'cfm__when-note--bad' : ''}`}>
                      {pickupPast ? 'Giờ giao không được ở quá khứ.' : <>Giao lúc: <strong>{formatPickupLong(pickup)}</strong></>}
                    </div>
                  </div>
                </div>
              ) : (
                /* BƯỚC 2 — Thanh toán (toàn nút bấm, không nhập text → bàn phím không bật) */
                <div className="cfm__pay">
                  <div className="cfm__sum">
                    <div className="adj__row"><span>Tạm tính</span><span>{formatVND(total)}</span></div>
                    {surAmount > 0 && <div className="adj__row"><span>+ Phụ thu</span><span>{formatVND(surAmount)}</span></div>}
                    {disAmount > 0 && <div className="adj__row adj__row--minus"><span>− Giảm</span><span>−{formatVND(disAmount)}</span></div>}
                    <div className="adj__row adj__row--total"><span>Tổng cộng</span><span>{formatVND(grandTotal)}</span></div>
                  </div>

                  {/* Phụ thu/giảm ẩn sau "Thêm" (ít dùng) */}
                  <div className="cfm__adjtoggle">
                    <span>+ Phụ thu / giảm giá</span>
                    <button type="button" className="cfm__addlink" onClick={() => setAdjOpen((o) => !o)}>
                      {adjOpen ? 'Ẩn' : 'Thêm'}
                    </button>
                  </div>
                  {adjOpen && (
                    <div className="cfm__adj">
                      <div className="cfm__tabs">
                        <button type="button" className={`cfm__tab ${adjTab === 'discount' ? 'cfm__tab--active' : ''}`} onClick={() => setAdjTab('discount')}>Giảm giá {disAuto && <span className="badge-auto">tự áp</span>}</button>
                        <button type="button" className={`cfm__tab ${adjTab === 'surcharge' ? 'cfm__tab--active' : ''}`} onClick={() => setAdjTab('surcharge')}>Phụ thu {surAuto && <span className="badge-auto">tự áp</span>}</button>
                      </div>
                      {adjTab === 'discount' ? (
                        <>
                          <div className="cfm__adj-row">
                            <input className="input" type="number" min="0" inputMode="decimal" placeholder={disType === 'percent' ? 'VD 10' : 'VD 20000'} value={disValue} onChange={(e) => setDisValue(e.target.value)} />
                            <div className="seg seg--sm">
                              <button type="button" className={`seg__btn ${disType === 'percent' ? 'seg__btn--active' : ''}`} onClick={() => setDisType('percent')}>%</button>
                              <button type="button" className={`seg__btn ${disType === 'fixed' ? 'seg__btn--active' : ''}`} onClick={() => setDisType('fixed')}>đ</button>
                            </div>
                          </div>
                          <input className="input adj__reason" type="text" placeholder="Lý do (tùy chọn)" value={disReason} onChange={(e) => setDisReason(e.target.value)} />
                        </>
                      ) : (
                        <>
                          <div className="cfm__adj-row">
                            <input className="input" type="number" min="0" inputMode="decimal" placeholder={surType === 'percent' ? 'VD 10' : 'VD 20000'} value={surValue} onChange={(e) => setSurValue(e.target.value)} />
                            <div className="seg seg--sm">
                              <button type="button" className={`seg__btn ${surType === 'percent' ? 'seg__btn--active' : ''}`} onClick={() => setSurType('percent')}>%</button>
                              <button type="button" className={`seg__btn ${surType === 'fixed' ? 'seg__btn--active' : ''}`} onClick={() => setSurType('fixed')}>đ</button>
                            </div>
                          </div>
                          <input className="input adj__reason" type="text" placeholder="Lý do (tùy chọn)" value={surReason} onChange={(e) => setSurReason(e.target.value)} />
                        </>
                      )}
                    </div>
                  )}

                  <div className="cfm__paygroup">
                    <span className="field-label">Thời điểm thu</span>
                    <div className="seg">
                      <button type="button" className={`seg__btn ${payMode === 'prepay' ? 'seg__btn--active' : ''}`} onClick={() => setPayMode('prepay')}>Thu trước</button>
                      <button type="button" className={`seg__btn ${payMode === 'later' ? 'seg__btn--active' : ''}`} onClick={() => setPayMode('later')}>Thu sau</button>
                    </div>
                    {payMode === 'prepay' && (
                      <>
                        <span className="field-label">Phương thức</span>
                        <div className="method-grid">
                          {PREPAY_METHODS.map((m) => (
                            <button type="button" key={m} className={`method-btn ${payMethod === m ? 'method-btn--active' : ''}`} onClick={() => setPayMethod(m)}>{PAYMENT_METHOD[m]}</button>
                          ))}
                        </div>
                        <p className="paystep__note">Thu đủ <strong>{formatVND(grandTotal)}</strong> khi tạo đơn.</p>
                      </>
                    )}
                  </div>
                </div>
              )}
            </div>

            {error && <div className="alert alert--error cfm__error">{error}</div>}

            <div className="cfm__actions">
              {step === 1 ? (
                <>
                  <button className="btn btn--ghost cfm__more" onClick={addMoreServices} disabled={busy}>
                    ← Thêm dịch vụ
                  </button>
                  <button className="btn btn--primary cfm__submit" onClick={goStep2}>
                    Tiếp · Thanh toán →
                  </button>
                </>
              ) : (
                <>
                  <button className="btn btn--ghost" onClick={() => { setStep(1); setError('') }} disabled={busy}>
                    ← Quay lại
                  </button>
                  <button className="btn btn--ghost cfm__more" onClick={addMoreServices} disabled={busy}>
                    ＋ Thêm dịch vụ
                  </button>
                  <button className="btn btn--primary cfm__submit" onClick={submit}
                    disabled={busy || isPastVnWall(pickup) || subExpired}
                    title={subExpired ? 'Gói hết hạn, không tạo đơn mới được' : undefined}>
                    {busy
                      ? 'Đang tạo…'
                      : subExpired
                        ? 'Gói hết hạn — không tạo đơn'
                        : payMode === 'prepay'
                          ? `Tạo & thu · ${formatVND(grandTotal)}`
                          : `Tạo đơn · ${formatVND(grandTotal)}`}
                  </button>
                </>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
