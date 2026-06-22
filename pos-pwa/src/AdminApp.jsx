import { Navigate, Route, Routes } from 'react-router-dom'
import AdminLayout from './components/AdminLayout'
import AdminProtectedRoute from './components/AdminProtectedRoute'
import { AdminAuthProvider } from './context/AdminAuthContext'
import AdminLogin from './pages/admin/AdminLogin'
import AdminTenantDetail from './pages/admin/AdminTenantDetail'
import AdminTenants from './pages/admin/AdminTenants'

// Khu /admin — TÁCH HẲN POS: AdminAuthProvider + route con riêng + AdminLayout.
// Mount tại App.jsx qua <Route path="/admin/*" element={<AdminApp/>}/>.
function Guarded({ children }) {
  return (
    <AdminProtectedRoute>
      <AdminLayout>{children}</AdminLayout>
    </AdminProtectedRoute>
  )
}

export default function AdminApp() {
  return (
    <AdminAuthProvider>
      <Routes>
        <Route path="login" element={<AdminLogin />} />
        <Route path="" element={<Guarded><AdminTenants /></Guarded>} />
        <Route path="tenants/:id" element={<Guarded><AdminTenantDetail /></Guarded>} />
        {/* Route lạ trong /admin → về danh sách (KHÔNG rơi ra catch-all POS). */}
        <Route path="*" element={<Navigate to="/admin" replace />} />
      </Routes>
    </AdminAuthProvider>
  )
}
