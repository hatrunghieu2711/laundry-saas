// Ô nhập tiền: bàn phím số, format nghìn (dấu chấm) ngay khi gõ.
// value: number | '' ; onChange(nextValue: number | '').
const fmt = new Intl.NumberFormat('vi-VN')

export default function MoneyInput({ value, onChange, ...rest }) {
  const display = value === '' || value == null ? '' : fmt.format(value)

  const handle = (e) => {
    const digits = e.target.value.replace(/\D/g, '')
    onChange(digits === '' ? '' : Number(digits))
  }

  return (
    <div className="money-input">
      <input
        className="input input--money"
        type="text"
        inputMode="numeric"
        autoComplete="off"
        value={display}
        onChange={handle}
        {...rest}
      />
      <span className="money-input__suffix">đ</span>
    </div>
  )
}
