import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import { BranchProvider } from './context/BranchContext'
import { TopbarSlotProvider } from './context/TopbarSlotContext'
import Board from './pages/Board'
import BranchesManage from './pages/BranchesManage'
import CashBook from './pages/CashBook'
import CategoriesManage from './pages/CategoriesManage'
import Login from './pages/Login'
import OrderDetail from './pages/OrderDetail'
import OrderNew from './pages/OrderNew'
import OrderPay from './pages/OrderPay'
import OrderSearch from './pages/OrderSearch'
import PriceRulesManage from './pages/PriceRulesManage'
import ReceiptSettings from './pages/ReceiptSettings'
import Reports from './pages/Reports'
import UsersManage from './pages/UsersManage'
import ServicesManage from './pages/ServicesManage'
import Shift from './pages/Shift'

function Protected({ children }) {
  return (
    <ProtectedRoute>
      <BranchProvider>
        <TopbarSlotProvider>
          <Layout>{children}</Layout>
        </TopbarSlotProvider>
      </BranchProvider>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><Shift /></Protected>} />
      <Route path="/board" element={<Protected><Board /></Protected>} />
      <Route path="/cashbook" element={<Protected><CashBook /></Protected>} />
      {/* "Đơn hàng" gộp vào /board (Stage 3.9) — /orders cũ redirect. */}
      <Route path="/orders" element={<Navigate to="/board" replace />} />
      <Route path="/search" element={<Protected><OrderSearch /></Protected>} />
      <Route path="/orders/new" element={<Protected><OrderNew /></Protected>} />
      <Route path="/orders/:id" element={<Protected><OrderDetail /></Protected>} />
      <Route path="/orders/:id/pay" element={<Protected><OrderPay /></Protected>} />
      <Route path="/services" element={<Protected><ServicesManage /></Protected>} />
      <Route path="/categories" element={<Protected><CategoriesManage /></Protected>} />
      <Route path="/price-rules" element={<Protected><PriceRulesManage /></Protected>} />
      <Route path="/users" element={<Protected><UsersManage /></Protected>} />
      <Route path="/branches" element={<Protected><BranchesManage /></Protected>} />
      <Route path="/reports" element={<Protected><Reports /></Protected>} />
      <Route path="/settings/receipt" element={<Protected><ReceiptSettings /></Protected>} />
      {/* Mặc định: route lạ → về trang chủ (guard sẽ đẩy ra /login nếu chưa đăng nhập). */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
