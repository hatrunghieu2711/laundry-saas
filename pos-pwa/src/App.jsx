import { Navigate, Route, Routes } from 'react-router-dom'
import AdminApp from './AdminApp'
import Layout from './components/Layout'
import PlatformBadge from './components/PlatformBadge' // ⚠️ TẠM — badge test môi trường, gỡ sau
import NativePrintLayer from './components/NativePrintLayer'
import ProtectedRoute from './components/ProtectedRoute'
import { BranchProvider } from './context/BranchContext'
import { ShiftProvider } from './context/ShiftContext'
import { TopbarSlotProvider } from './context/TopbarSlotContext'
import Board from './pages/Board'
import BranchesManage from './pages/BranchesManage'
import Catalog from './pages/Catalog'
import CashBook from './pages/CashBook'
import ChangePassword from './pages/ChangePassword'
import Login from './pages/Login'
import OrderDetail from './pages/OrderDetail'
import OrderNew from './pages/OrderNew'
import OrderPay from './pages/OrderPay'
import History from './pages/History'
import ReceiptSettings from './pages/ReceiptSettings'
import Reports from './pages/Reports'
import ShopSettings from './pages/ShopSettings'
import UsersManage from './pages/UsersManage'
import Shift from './pages/Shift'

// Subdomain admin.* (vd admin.giatui.app) → CHỈ khu /admin (cùng 1 bundle SPA).
// Host thường (giatui.app/localhost/…) → POS như cũ. KHÔNG host POS hợp lệ nào bắt đầu 'admin.'.
const ADMIN_HOST = window.location.hostname.startsWith('admin.')

function Protected({ children }) {
  return (
    <ProtectedRoute>
      <BranchProvider>
        <ShiftProvider>
          <TopbarSlotProvider>
            <Layout>{children}</Layout>
          </TopbarSlotProvider>
        </ShiftProvider>
      </BranchProvider>
    </ProtectedRoute>
  )
}

export default function App() {
  // Host admin.* → CHỈ đăng ký /admin: route POS không tồn tại → chặn POS tự nhiên;
  // mọi path khác → /admin (AdminProtectedRoute tự đẩy /admin/login nếu chưa đăng nhập).
  if (ADMIN_HOST) {
    return (
      <>
        <Routes>
          <Route path="/admin/*" element={<AdminApp />} />
          <Route path="*" element={<Navigate to="/admin" replace />} />
        </Routes>
        <PlatformBadge /> {/* ⚠️ TẠM — gỡ sau */}
      </>
    )
  }
  return (
    <>
    <Routes>
      {/* Khu Super Admin — TÁCH HẲN POS (auth/layout/token riêng). Đặt TRƯỚC catch-all. */}
      <Route path="/admin/*" element={<AdminApp />} />
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><Shift /></Protected>} />
      <Route path="/board" element={<Protected><Board /></Protected>} />
      <Route path="/cashbook" element={<Protected><CashBook /></Protected>} />
      {/* "Đơn hàng" gộp vào /board (Stage 3.9) — /orders cũ redirect. */}
      <Route path="/orders" element={<Navigate to="/board" replace />} />
      {/* "Tra cứu" gộp vào "Lịch sử" (Stage 6.38) — /search cũ redirect. */}
      <Route path="/history" element={<Protected><History /></Protected>} />
      <Route path="/search" element={<Navigate to="/history" replace />} />
      <Route path="/orders/new" element={<Protected><OrderNew /></Protected>} />
      <Route path="/orders/:id" element={<Protected><OrderDetail /></Protected>} />
      <Route path="/orders/:id/pay" element={<Protected><OrderPay /></Protected>} />
      {/* Hub gom 4 màn quản lý dịch vụ vào 1 (tab ?tab=). Route cũ redirect vào hub. */}
      <Route path="/catalog" element={<Protected><Catalog /></Protected>} />
      <Route path="/services" element={<Navigate to="/catalog?tab=services" replace />} />
      <Route path="/categories" element={<Navigate to="/catalog?tab=categories" replace />} />
      <Route path="/price-rules" element={<Navigate to="/catalog?tab=price-rules" replace />} />
      <Route path="/services/visibility" element={<Navigate to="/catalog?tab=visibility" replace />} />
      <Route path="/users" element={<Protected><UsersManage /></Protected>} />
      <Route path="/branches" element={<Protected><BranchesManage /></Protected>} />
      <Route path="/reports" element={<Protected><Reports /></Protected>} />
      <Route path="/settings/receipt" element={<Protected><ReceiptSettings /></Protected>} />
      <Route path="/account/password" element={<Protected><ChangePassword /></Protected>} />
      <Route path="/settings/shop" element={<Protected><ShopSettings /></Protected>} />
      {/* Mặc định: route lạ → về trang chủ (guard sẽ đẩy ra /login nếu chưa đăng nhập). */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
    <NativePrintLayer />
    <PlatformBadge /> {/* ⚠️ TẠM — gỡ sau */}
    </>
  )
}
