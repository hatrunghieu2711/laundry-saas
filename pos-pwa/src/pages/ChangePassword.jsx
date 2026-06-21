import { useState } from 'react'
import { ApiError, api } from '../lib/api'

// Tự đổi mật khẩu (self-service). Bắt MK hiện tại + nhập lại MK mới (khớp) + min 6.
// Đổi xong: BE đăng xuất các thiết bị khác, thiết bị này GIỮ phiên (không bị đá ra).
export default function ChangePassword() {
  const [current, setCurrent] = useState('')
  const [next, setNext] = useState('')
  const [confirm, setConfirm] = useState('')
  const [error, setError] = useState('')
  const [done, setDone] = useState(false)
  const [busy, setBusy] = useState(false)

  const onSubmit = async (e) => {
    e.preventDefault()
    setError('')
    setDone(false)
    if (next.length < 6) {
      setError('Mật khẩu mới tối thiểu 6 ký tự.')
      return
    }
    if (next !== confirm) {
      setError('Nhập lại mật khẩu mới không khớp.')
      return
    }
    setBusy(true)
    try {
      await api.changePassword(current, next)
      setDone(true)
      setCurrent('')
      setNext('')
      setConfirm('')
    } catch (err) {
      if (err instanceof ApiError && err.code === 'INVALID_CURRENT_PASSWORD') {
        setError('Mật khẩu hiện tại không đúng.')
      } else if (err instanceof ApiError) {
        setError(err.message)
      } else {
        setError('Không kết nối được máy chủ. Thử lại.')
      }
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="shift">
      <form className="shift__card" onSubmit={onSubmit} style={{ maxWidth: 460 }}>
        <h2 className="shift__card-title">Đổi mật khẩu</h2>
        <p className="shift__hint">
          Sau khi đổi, các thiết bị khác sẽ bị đăng xuất; thiết bị này vẫn giữ đăng nhập.
        </p>

        <label className="field">
          <span>Mật khẩu hiện tại</span>
          <input
            className="input"
            type="password"
            autoComplete="current-password"
            value={current}
            onChange={(e) => setCurrent(e.target.value)}
            required
            autoFocus
          />
        </label>

        <label className="field">
          <span>Mật khẩu mới (tối thiểu 6 ký tự)</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={next}
            onChange={(e) => setNext(e.target.value)}
            required
          />
        </label>

        <label className="field">
          <span>Nhập lại mật khẩu mới</span>
          <input
            className="input"
            type="password"
            autoComplete="new-password"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
            required
          />
        </label>

        {error && <div className="alert alert--error">{error}</div>}
        {done && (
          <div className="alert alert--success">
            Đã đổi mật khẩu. Các thiết bị khác đã được đăng xuất.
          </div>
        )}

        <button className="btn btn--primary btn--block" type="submit" disabled={busy}>
          {busy ? 'Đang đổi…' : 'Đổi mật khẩu'}
        </button>
      </form>
    </div>
  )
}
