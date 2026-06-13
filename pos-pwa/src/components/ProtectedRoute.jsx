import { Navigate, useLocation } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'

// Route guard: chưa login → về /login (nhớ vị trí muốn tới).
export default function ProtectedRoute({ children }) {
  const { user } = useAuth()
  const location = useLocation()
  if (!user) {
    return <Navigate to="/login" replace state={{ from: location }} />
  }
  return children
}
