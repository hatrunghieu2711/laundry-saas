"""Telegram notification khi đóng ca.

- Cấu hình per-tenant trong bảng `tenant_settings` (bot token, owner chat_id,
  ngưỡng lệch két).
- Gửi SAU khi đóng ca đã commit. Lỗi gửi KHÔNG được làm fail việc đóng ca:
  notify_shift_closed nuốt mọi exception và chỉ log.
"""
import logging
from datetime import timedelta, timezone

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branch import Branch
from app.models.tenant_settings import TenantSettings
from app.models.user import User

logger = logging.getLogger(__name__)

_TELEGRAM_API = "https://api.telegram.org/bot{token}/sendMessage"
# Giờ Việt Nam (UTC+7, không DST) — dùng offset cố định để khỏi phụ thuộc tzdata.
_VN_TZ = timezone(timedelta(hours=7))


def _vnd(value) -> str:
    """Định dạng tiền VND: 100000 -> '100.000đ'."""
    return f"{int(value or 0):,}".replace(",", ".") + "đ"


def _vnd_signed(value) -> str:
    """Có dấu: 50000 -> '+50.000đ', -50000 -> '-50.000đ'."""
    return f"{int(value or 0):+,}".replace(",", ".") + "đ"


def build_shift_close_message(
    *, branch_name: str, closed_by_name: str, shift, threshold
) -> str:
    """Dựng nội dung message tiếng Việt cho sự kiện đóng ca.

    Nếu |cash_difference| > threshold thì thêm cảnh báo ⚠️ LỆCH KÉT lên đầu.
    """
    diff = int(shift.cash_difference or 0)
    over_threshold = abs(diff) > int(threshold or 0)

    closed_at = shift.closed_at
    # closed_at lưu UTC; hiển thị giờ VN cho owner.
    closed_str = (
        closed_at.astimezone(_VN_TZ).strftime("%H:%M %d/%m/%Y") if closed_at else "?"
    )

    lines = [
        f"🧾 <b>ĐÓNG CA</b> — {branch_name}",
        f"👤 Người đóng: {closed_by_name}",
        f"🕒 Giờ đóng: {closed_str}",
        "",
        f"💰 Đầu ca: {_vnd(shift.opening_cash)}",
        f"— Tiền mặt: {_vnd(shift.total_cash)}",
        f"— Chuyển khoản: {_vnd(shift.total_transfer)}",
        f"— QR: {_vnd(shift.total_qr)}",
        f"— COD: {_vnd(shift.total_cod)}",
        f"🧺 Số đơn: {int(shift.orders_count or 0)}",
    ]

    # Sổ quỹ thu-chi tiền mặt ngoài dịch vụ (chỉ hiện khi có) — để owner thấy đủ
    # dòng tiền vào/ra két ngoài doanh thu đơn.
    income = int(shift.total_income or 0)
    expense = int(shift.total_expense or 0)
    if income or expense:
        lines.append("")
        if income:
            lines.append(f"➕ Thu khác (tiền mặt): {_vnd(income)}")
        if expense:
            lines.append(f"➖ Chi (tiền mặt): {_vnd(expense)}")

    lines += [
        "",
        f"📊 Dự kiến cuối ca: {_vnd(shift.closing_cash_expected)}",
        f"📥 Thực tế đếm: {_vnd(shift.closing_cash_actual)}",
        f"<b>⚖️ Lệch két: {_vnd_signed(diff)}</b>",
    ]
    if over_threshold:
        warn = f"⚠️ <b>LỆCH KÉT</b> vượt ngưỡng {_vnd(threshold)} ⚠️"
        lines = [warn, ""] + lines
    return "\n".join(lines)


async def send_message(bot_token: str, chat_id: str, text: str) -> None:
    """Gọi Telegram Bot API. Raise nếu lỗi (caller chịu trách nhiệm nuốt)."""
    url = _TELEGRAM_API.format(token=bot_token)
    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.post(
            url, json={"chat_id": chat_id, "text": text, "parse_mode": "HTML"}
        )
        resp.raise_for_status()


async def notify_shift_closed(db: AsyncSession, shift) -> None:
    """Gửi thông báo đóng ca cho owner. Nuốt MỌI lỗi (không fail đóng ca)."""
    try:
        settings = await db.get(TenantSettings, shift.tenant_id)
        if not settings or not settings.telegram_bot_token or not settings.telegram_owner_chat_id:
            return  # tenant chưa cấu hình Telegram -> bỏ qua

        branch = await db.get(Branch, shift.branch_id)
        closer = await db.get(User, shift.closed_by) if shift.closed_by else None
        message = build_shift_close_message(
            branch_name=branch.name if branch else "?",
            closed_by_name=closer.full_name if closer else "?",
            shift=shift,
            threshold=settings.cash_diff_threshold,
        )
        await send_message(
            settings.telegram_bot_token, settings.telegram_owner_chat_id, message
        )
    except Exception:  # noqa: BLE001 — chủ ý nuốt, không để fail đóng ca
        logger.exception("Gửi Telegram thông báo đóng ca thất bại (bỏ qua)")
