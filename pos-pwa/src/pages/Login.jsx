import { useState } from 'react'
import { useLocation, useNavigate } from 'react-router-dom'
import { useAuth } from '../context/AuthContext'
import { ApiError } from '../lib/api'
import { getTenantSlug, setTenantSlug } from '../lib/storage'

// Điều hướng theo role sau khi đăng nhập.
function homeFor() {
  // Stage 3a: tất cả role về trang chủ POS; phân nhánh chi tiết ở phase sau.
  return '/'
}

export default function Login() {
  const { login } = useAuth()
  const navigate = useNavigate()
  const location = useLocation()
  const [phone, setPhone] = useState('')
  const [password, setPassword] = useState('')
  // Mã cửa hàng (slug tenant) — tự điền từ máy nếu đã lưu (6.76, giai đoạn 1: optional).
  const [slug, setSlug] = useState(() => getTenantSlug())
  const [error, setError] = useState('')
  const [loading, setLoading] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setLoading(true)
    const slugClean = slug.trim().toLowerCase()
    try {
      const user = await login(phone.trim(), password, slugClean)
      // Đăng nhập OK → nhớ mã trên máy này (bền qua logout); rỗng → xóa mã đã lưu.
      setTenantSlug(slugClean)
      const dest = location.state?.from?.pathname || homeFor(user.role)
      navigate(dest, { replace: true })
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
        {/* Pre-login CHƯA biết tenant → tiêu đề/logo GIỮ generic (không hardcode tên tiệm). */}
        <div className="login__logo">POS</div>
        <h1 className="login__title">Đăng nhập</h1>
        <p className="login__sub">Đăng nhập để bắt đầu ca làm</p>

        <label className="field">
          <span>Số điện thoại</span>
          <input
            className="input"
            type="tel"
            inputMode="numeric"
            autoComplete="username"
            value={phone}
            onChange={(e) => setPhone(e.target.value)}
            placeholder="0900000001"
            required
            autoFocus
          />
        </label>

        <label className="field">
          <span>Mật khẩu</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            placeholder="••••••••"
            required
          />
        </label>

        <label className="field">
          <span>Mã cửa hàng</span>
          <input
            className="input"
            type="text"
            inputMode="text"
            autoCapitalize="none"
            autoCorrect="off"
            spellCheck={false}
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="vd: giat-ui-2h"
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
