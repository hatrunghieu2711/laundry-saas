import { useState } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { useAdminAuth } from '../../context/AdminAuthContext'
import { ApiError } from '../../lib/api'

// Đăng nhập Super Admin — sao y .login__card (Login.jsx POS), khác text + dùng api.admin.
export default function AdminLogin() {
  const { admin, login } = useAdminAuth()
  const navigate = useNavigate()
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  // Đã đăng nhập admin → vào thẳng danh sách.
  if (admin) return <Navigate to="/admin" replace />

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    try {
      await login(phone.trim(), password)
      navigate('/admin', { replace: true })
    } catch (err) {
      if (err instanceof ApiError && err.code === 'INVALID_CREDENTIALS') {
        setError('Sai số điện thoại hoặc mật khẩu.')
      } else if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Không kết nối được máy chủ. Kiểm tra mạng rồi thử lại.')
      }
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="login">
      <form className="login__card" onSubmit={onSubmit}>
        <div className="login__logo">QT</div>
        <h1 className="login__title">Quản trị hệ thống</h1>
        <p className="login__sub">Đăng nhập Super Admin</p>

        <label className="field">
          <span>Số điện thoại</span>
          <input
            className="input" type="tel" inputMode="numeric" autoComplete="username"
            value={phone} onChange={(e) => setPhone(e.target.value)}
            placeholder="0900000000" required autoFocus
          />
        </label>

        <label className="field">
          <span>Mật khẩu</span>
          <input
            className="input" type="password" autoComplete="current-password"
            value={password} onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••" required
          />
        </label>

        {error && <div className="alert alert--error">{error}</div>}

        <button className="btn btn--primary btn--block" type="submit" disabled={loading}>
          {loading ? 'Đang đăng nhập…' : 'Đăng nhập'}
        </button>
      </form>
    </div>
  )
}
