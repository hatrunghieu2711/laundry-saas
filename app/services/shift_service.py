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

from sqlalchemy import case, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.cash_transaction import CashTransaction
from app.models.order import Order
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
    db: AsyncSession,
    actor: User,
    shift_id: uuid.UUID,
    closing_cash_actual: Decimal,
    handover_to_owner: Decimal = Decimal(0),
    cash_diff_reason: str | None = None,
) -> Shift:
    shift = await _get_shift_in_tenant(db, actor, shift_id)
    if shift.status == "closed":
        raise APIError(409, "SHIFT_CLOSED", "Ca đã đóng, không thể thao tác")
    # Rút nộp chủ KHÔNG được vượt tiền thực đếm (không rút quá số có trong két).
    if handover_to_owner > closing_cash_actual:
        raise APIError(
            422, "HANDOVER_EXCEEDS_CASH",
            "Số tiền nộp chủ không được vượt quá tiền mặt thực đếm",
        )

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

    # Sổ quỹ thu-chi TIỀN MẶT của ca — phần ảnh hưởng KÉT (transfer/qr không vào két).
    def _ct_cash_sum(ttype: str):
        return func.coalesce(
            func.sum(CashTransaction.amount).filter(
                CashTransaction.type == ttype,
                CashTransaction.payment_method == "cash",
            ),
            _ZERO,
        )

    ct = (
        await db.execute(
            select(
                _ct_cash_sum("income").label("income"),
                _ct_cash_sum("expense").label("expense"),
            ).where(CashTransaction.shift_id == shift.id)
        )
    ).one()

    # Két cuối ca = đầu ca + tiền mặt thu đơn + thu tiền mặt - chi tiền mặt.
    expected = shift.opening_cash + row.cash + ct.income - ct.expense
    cash_difference = closing_cash_actual - expected
    # ĐAI AN TOÀN (lớp 2 sau FE 6.32): LỆCH tiền → BẮT BUỘC lý do. Raise TRƯỚC khi đổi
    # bất kỳ field nào (ca giữ nguyên 'open', không đóng nửa vời). Khớp két (diff=0) → cho None.
    reason = (cash_diff_reason or "").strip()
    if cash_difference != 0 and not reason:
        raise APIError(
            422, "CASH_DIFF_REASON_REQUIRED",
            "Lệch tiền — bắt buộc nhập lý do lệch trước khi đóng ca",
        )
    shift.total_cash = row.cash
    shift.total_transfer = row.transfer
    shift.total_qr = row.qr
    shift.total_cod = row.cod
    shift.total_income = ct.income
    shift.total_expense = ct.expense
    shift.orders_count = row.orders_count
    shift.closing_cash_expected = expected
    shift.closing_cash_actual = closing_cash_actual
    shift.cash_difference = cash_difference
    shift.cash_diff_reason = reason or None
    # Rút nộp chủ: bước SAU đối soát — rút từ TIỀN THỰC ĐẾM (đã khớp), KHÔNG nằm
    # trong công thức expected (không phải chi phí, không ảnh hưởng doanh thu).
    shift.handover_to_owner = handover_to_owner
    shift.cash_left_for_next = closing_cash_actual - handover_to_owner
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


async def opening_suggestion(
    db: AsyncSession, actor: User, branch_id: uuid.UUID | None
) -> Decimal:
    """Gợi ý đầu ca = cash_left_for_next của ca ĐÓNG gần nhất cùng branch (nhân
    viên ĐẾM LẠI rồi xác nhận/sửa — KHÔNG tự lấy cứng). Chưa có ca đóng → 0."""
    branch_id = _resolve_branch(actor, branch_id)
    last = await db.scalar(
        select(Shift)
        .where(
            Shift.tenant_id == actor.tenant_id,
            Shift.branch_id == branch_id,
            Shift.status == "closed",
        )
        .order_by(Shift.closed_at.desc())
        .limit(1)
    )
    if last is None or last.cash_left_for_next is None:
        return Decimal(0)
    return last.cash_left_for_next


async def shift_summary(db: AsyncSession, actor: User, shift_id: uuid.UUID) -> dict:
    """Chỉ số REALTIME của ca (Stage 6.1). cash_in_drawer dùng ĐÚNG công thức
    reconciliation (close_shift) để nhất quán lúc đóng ca.

    PHÂN BIỆT (KHÔNG phải bug khi 2 số lệch):
    - total_collected = TIỀN THU trong ca này (mọi payment cash+transfer+qr theo
      shift_id) — GỒM đơn nợ ca TRƯỚC được thu ca này ("ai thu người đó ghi nhận").
    - shift_revenue = DOANH THU ca này = SUM(total_amount) đơn TẠO trong ca
      (created_at ∈ ca, cùng branch, trừ đơn đã hủy) — kể cả đơn còn nợ chưa thu.
    """
    shift = await _get_shift_in_tenant(db, actor, shift_id)

    def _sum(method: str):
        return func.coalesce(
            func.sum(Payment.amount).filter(Payment.payment_method == method), _ZERO
        )

    pay = (
        await db.execute(
            select(
                _sum("cash").label("cash"),
                _sum("transfer").label("transfer"),
                _sum("qr").label("qr"),
            ).where(Payment.shift_id == shift.id)
        )
    ).one()

    def _ct_cash(ttype: str):
        return func.coalesce(
            func.sum(CashTransaction.amount).filter(
                CashTransaction.type == ttype,
                CashTransaction.payment_method == "cash",
            ),
            _ZERO,
        )

    ct = (
        await db.execute(
            select(_ct_cash("income").label("income"), _ct_cash("expense").label("expense"))
            .where(CashTransaction.shift_id == shift.id)
        )
    ).one()

    # Doanh thu theo ca TẠO đơn: created_at ∈ [opened_at, closed_at|now], cùng branch.
    # Stage 6.28 — SỔ CÂN: đơn KHÔNG hủy đóng góp total_amount (kể cả còn nợ = dự kiến);
    # đơn HỦY đóng góp phần GIỮ LẠI = net payments (= đã thu − đã hoàn). KHÔNG còn loại
    # sạch đơn cancelled khỏi doanh thu. order_count vẫn CHỈ đếm đơn không hủy.
    paid_sq = (
        select(Payment.order_id, func.sum(Payment.amount).label("net"))
        .group_by(Payment.order_id)
        .subquery()
    )
    contrib = case(
        (Order.order_status != "cancelled", Order.total_amount),
        else_=func.coalesce(paid_sq.c.net, _ZERO),
    )
    rev_q = (
        select(
            func.coalesce(func.sum(contrib), _ZERO).label("revenue"),
            func.count().filter(Order.order_status != "cancelled").label("cnt"),
        )
        .select_from(Order)
        .outerjoin(paid_sq, Order.id == paid_sq.c.order_id)
        .where(
            Order.tenant_id == shift.tenant_id,
            Order.branch_id == shift.branch_id,
            Order.created_at >= shift.opened_at,
        )
    )
    if shift.closed_at is not None:
        rev_q = rev_q.where(Order.created_at <= shift.closed_at)
    rev = (await db.execute(rev_q)).one()

    return {
        "shift_id": shift.id,
        "status": shift.status,
        "opening_cash": shift.opening_cash,
        # Két = đầu ca + tiền mặt thu đơn + thu quỹ cash − chi quỹ cash (= expected đóng ca).
        "cash_in_drawer": shift.opening_cash + pay.cash + ct.income - ct.expense,
        "transfer_total": pay.transfer + pay.qr,
        "total_collected": pay.cash + pay.transfer + pay.qr,
        "shift_revenue": rev.revenue,
        "order_count": rev.cnt,
    }


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
