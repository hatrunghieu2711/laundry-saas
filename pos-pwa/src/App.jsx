import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Login from './pages/Login'
import OrderDetail from './pages/OrderDetail'
import OrderNew from './pages/OrderNew'
import OrderPay from './pages/OrderPay'
import OrdersList from './pages/OrdersList'
import ServicesManage from './pages/ServicesManage'
import Shift from './pages/Shift'

function Protected({ children }) {
  return (
    <ProtectedRoute>
      <Layout>{children}</Layout>
    </ProtectedRoute>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route path="/" element={<Protected><Shift /></Protected>} />
      <Route path="/orders" element={<Protected><OrdersList /></Protected>} />
      <Route path="/orders/new" element={<Protected><OrderNew /></Protected>} />
      <Route path="/orders/:id" element={<Protected><OrderDetail /></Protected>} />
      <Route path="/orders/:id/pay" element={<Protected><OrderPay /></Protected>} />
      <Route path="/services" element={<Protected><ServicesManage /></Protected>} />
      {/* Mặc định: route lạ → về trang chủ (guard sẽ đẩy ra /login nếu chưa đăng nhập). */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
