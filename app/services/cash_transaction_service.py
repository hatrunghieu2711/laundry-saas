"""Sổ quỹ thu-chi (cash_transactions) — Stage 4.2. IMMUTABLE (INSERT only).

QUY TẮC (CLAUDE.md TÀI CHÍNH, áp cho thu/chi ngoài đơn):
- Mọi giao dịch PHẢI thuộc một shift đang OPEN tại branch thao tác (NOT NULL).
- branch phân giải qua scope.resolve_write_branch (owner truyền; staff lấy token).
- amount là MAGNITUDE > 0 (422 INVALID_AMOUNT nếu <=0); dấu do `type`.
- category bắt buộc không rỗng (422 CATEGORY_REQUIRED).
- Sửa sai = ghi giao dịch đối ứng (trigger DB chặn UPDATE/DELETE).
"""
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.cash_transaction import CashTransaction
from app.models.shift import Shift
from app.models.user import User
from app.services import scope


async def create_cash_transaction(
    db: AsyncSession,
    actor: User,
    *,
    type: str,
    amount: Decimal,
    category: str,
    note: str | None,
    payment_method: str,
    branch_id: uuid.UUID | None,
) -> CashTransaction:
    branch_id = scope.resolve_write_branch(actor, branch_id)

    if amount is None or amount <= 0:
        raise APIError(422, "INVALID_AMOUNT", "amount phải là số dương (magnitude)")
    mag = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)

    if not (category and category.strip()):
        raise APIError(422, "CATEGORY_REQUIRED", "category bắt buộc (danh mục thu/chi)")

    # Phải có ca đang OPEN tại branch thao tác.
    shift = await db.scalar(
        select(Shift).where(
            Shift.tenant_id == actor.tenant_id,
            Shift.branch_id == branch_id,
            Shift.status == "open",
        )
    )
    if shift is None:
        raise APIError(409, "NO_OPEN_SHIFT", "Chi nhánh chưa có ca đang mở")

    ct = CashTransaction(
        tenant_id=actor.tenant_id,
        branch_id=branch_id,
        shift_id=shift.id,
        type=type,
        amount=mag,
        category=category.strip(),
        note=(note.strip() if note and note.strip() else None),
        payment_method=payment_method,
        created_by=actor.id,
    )
    db.add(ct)
    await db.commit()
    return await get_cash_transaction(db, actor, ct.id)


async def get_cash_transaction(
    db: AsyncSession, actor: User, ct_id: uuid.UUID
) -> CashTransaction:
    ct = await db.scalar(
        select(CashTransaction).where(
            CashTransaction.tenant_id == actor.tenant_id,
            CashTransaction.id == ct_id,
        )
    )
    if ct is None or (actor.role != "owner" and ct.branch_id != actor.branch_id):
        raise APIError(404, "CASH_TRANSACTION_NOT_FOUND", "Không tìm thấy giao dịch quỹ")
    return ct


async def list_cash_transactions(
    db: AsyncSession,
    actor: User,
    page: Pagination,
    *,
    shift_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    type: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[CashTransaction], int]:
    base = select(CashTransaction).where(CashTransaction.tenant_id == actor.tenant_id)
    # staff/manager chỉ thấy branch mình; owner thấy toàn tenant (lọc theo branch_id nếu có).
    if actor.role != "owner":
        base = base.where(CashTransaction.branch_id == actor.branch_id)
    elif branch_id is not None:
        base = base.where(CashTransaction.branch_id == branch_id)
    if shift_id is not None:
        base = base.where(CashTransaction.shift_id == shift_id)
    if type is not None:
        base = base.where(CashTransaction.type == type)
    if date_from is not None:
        base = base.where(CashTransaction.created_at >= date_from)
    if date_to is not None:
        base = base.where(CashTransaction.created_at <= date_to)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(CashTransaction.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(result.scalars().all()), total
