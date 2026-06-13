"""Shift business logic: mở/đóng ca + reconciliation.

QUY TẮC (CLAUDE.md):
- Mỗi branch TỐI ĐA MỘT shift open (partial unique index ở DB là chốt cuối;
  service trả lỗi đẹp 409 trước).
- Shift đã closed là BẤT BIẾN: không sửa, không reopen, không thêm payment.
- Đóng ca = reconciliation, tính MỘT LẦN và lưu vĩnh viễn:
    closing_cash_expected = opening_cash + SUM(amount) payments method='cash'
    cash_difference       = closing_cash_actual - closing_cash_expected
    total_cash/transfer/qr/cod = SUM(amount) theo method
    orders_count          = COUNT(DISTINCT order_id)
  Toàn bộ trong MỘT transaction.
- Mọi query filter tenant_id (từ token).
"""
import uuid
from datetime import datetime, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.payment import Payment
from app.models.shift import Shift
from app.models.user import User
from app.services import branch_service, telegram_service

_ZERO = Decimal(0)


def _resolve_branch(actor: User, branch_id: uuid.UUID | None) -> uuid.UUID:
    """Branch để thao tác ca.

    - owner: BẮT BUỘC truyền branch_id.
    - staff/manager/shipper: dùng branch của mình; nếu truyền branch khác -> 403.
    """
    if actor.role == "owner":
        if branch_id is None:
            raise APIError(400, "BRANCH_REQUIRED", "Owner phải chỉ định branch_id")
        return branch_id
    if actor.branch_id is None:
        raise APIError(400, "BRANCH_REQUIRED", "Tài khoản chưa gắn chi nhánh")
    if branch_id is not None and branch_id != actor.branch_id:
        raise APIError(403, "FORBIDDEN", "Không thể thao tác ca ở chi nhánh khác")
    return actor.branch_id


async def _get_open_shift(
    db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID
) -> Shift | None:
    return await db.scalar(
        select(Shift).where(
            Shift.tenant_id == tenant_id,
            Shift.branch_id == branch_id,
            Shift.status == "open",
        )
    )


async def open_shift(
    db: AsyncSession, actor: User, opening_cash: Decimal, branch_id: uuid.UUID | None
) -> Shift:
    branch_id = _resolve_branch(actor, branch_id)
    # Xác minh branch thuộc tenant (và tồn tại) — reuse branch_service.
    await branch_service.get_branch(db, actor.tenant_id, branch_id)

    if await _get_open_shift(db, actor.tenant_id, branch_id) is not None:
        raise APIError(409, "SHIFT_ALREADY_OPEN", "Chi nhánh đã có ca đang mở")

    shift = Shift(
        tenant_id=actor.tenant_id,
        branch_id=branch_id,
        opened_by=actor.id,
        opening_cash=opening_cash,
        status="open",
    )
    db.add(shift)
    try:
        await db.commit()
    except IntegrityError as exc:
        # Chốt cuối: partial unique index one_open_shift_per_branch (race condition).
        await db.rollback()
        raise APIError(409, "SHIFT_ALREADY_OPEN", "Chi nhánh đã có ca đang mở") from exc
    return await get_shift(db, actor, shift.id)


async def _reload_shift(db: AsyncSession, shift_id: uuid.UUID) -> Shift:
    """Nạp lại shift kèm tên người mở/đóng (populate_existing để lấy giá trị mới
    sau khi set closed_by)."""
    result = await db.execute(
        select(Shift)
        .options(selectinload(Shift.opened_by_user), selectinload(Shift.closed_by_user))
        .where(Shift.id == shift_id)
        .execution_options(populate_existing=True)
    )
    return result.scalar_one()


async def _get_shift_in_tenant(
    db: AsyncSession, actor: User, shift_id: uuid.UUID
) -> Shift:
    shift = await db.scalar(
        select(Shift).where(Shift.tenant_id == actor.tenant_id, Shift.id == shift_id)
    )
    if shift is None:
        raise APIError(404, "SHIFT_NOT_FOUND", "Không tìm thấy ca")
    # staff/manager chỉ thao tác ca branch của mình.
    if actor.role != "owner" and shift.branch_id != actor.branch_id:
        raise APIError(403, "FORBIDDEN", "Không có quyền với ca ở chi nhánh khác")
    return shift


async def close_shift(
    db: AsyncSession, actor: User, shift_id: uuid.UUID, closing_cash_actual: Decimal
) -> Shift:
    shift = await _get_shift_in_tenant(db, actor, shift_id)
    if shift.status == "closed":
        raise APIError(409, "SHIFT_CLOSED", "Ca đã đóng, không thể thao tác")

    # Aggregate toàn bộ payments của ca trong MỘT query.
    def _sum(method: str):
        return func.coalesce(
            func.sum(Payment.amount).filter(Payment.payment_method == method), _ZERO
        )

    row = (
        await db.execute(
            select(
                _sum("cash").label("cash"),
                _sum("transfer").label("transfer"),
                _sum("qr").label("qr"),
                _sum("cod").label("cod"),
                func.count(func.distinct(Payment.order_id)).label("orders_count"),
            ).where(Payment.shift_id == shift.id)
        )
    ).one()

    expected = shift.opening_cash + row.cash
    shift.total_cash = row.cash
    shift.total_transfer = row.transfer
    shift.total_qr = row.qr
    shift.total_cod = row.cod
    shift.orders_count = row.orders_count
    shift.closing_cash_expected = expected
    shift.closing_cash_actual = closing_cash_actual
    shift.cash_difference = closing_cash_actual - expected
    shift.closed_by = actor.id
    shift.closed_at = datetime.now(timezone.utc)
    shift.status = "closed"

    await db.commit()

    # Thông báo Telegram SAU commit; lỗi gửi không làm fail đóng ca.
    await telegram_service.notify_shift_closed(db, shift)
    return await _reload_shift(db, shift.id)


async def get_current_shift(
    db: AsyncSession, actor: User, branch_id: uuid.UUID | None
) -> Shift:
    branch_id = _resolve_branch(actor, branch_id)
    shift = await _get_open_shift(db, actor.tenant_id, branch_id)
    if shift is None:
        raise APIError(404, "NO_OPEN_SHIFT", "Không có ca đang mở")
    return shift


async def get_shift(db: AsyncSession, actor: User, shift_id: uuid.UUID) -> Shift:
    return await _get_shift_in_tenant(db, actor, shift_id)


async def list_shifts(
    db: AsyncSession,
    actor: User,
    page: Pagination,
    *,
    branch_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[Shift], int]:
    base = select(Shift).where(Shift.tenant_id == actor.tenant_id)
    # staff/manager chỉ thấy ca branch mình; owner thấy toàn tenant (lọc theo branch_id nếu có).
    if actor.role != "owner":
        base = base.where(Shift.branch_id == actor.branch_id)
    elif branch_id is not None:
        base = base.where(Shift.branch_id == branch_id)
    if date_from is not None:
        base = base.where(Shift.opened_at >= date_from)
    if date_to is not None:
        base = base.where(Shift.opened_at <= date_to)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Shift.opened_at.desc()).limit(page.limit).offset(page.offset)
    )
    return list(result.scalars().all()), total
