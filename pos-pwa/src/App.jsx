import { Navigate, Route, Routes } from 'react-router-dom'
import Layout from './components/Layout'
import ProtectedRoute from './components/ProtectedRoute'
import Home from './pages/Home'
import Login from './pages/Login'

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <ProtectedRoute>
            <Layout>
              <Home />
            </Layout>
          </ProtectedRoute>
        }
      />
      {/* Mặc định: route lạ → về trang chủ (guard sẽ đẩy ra /login nếu chưa đăng nhập). */}
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  )
}
