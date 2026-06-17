"""Payment business logic — IMMUTABLE (INSERT only; DB trigger chặn update/delete).

QUY TẮC (CLAUDE.md TÀI CHÍNH):
- Mọi payment PHẢI thuộc một shift đang OPEN tại branch CỦA ĐƠN.
- branch_id/tenant_id/shift_id lấy từ order + ca, KHÔNG tin client.
- Sign convention: client gửi MAGNITUDE (>0); service áp dấu theo transaction_type:
    payment / resolve_debt / adjustment -> +mag
    refund / cancel_paid                -> -mag
    debt                                -> 0 (ghi nợ, chưa thu)
  amount <= 0 cho type khác debt -> 422 INVALID_AMOUNT (chặn "sai dấu").
- reason BẮT BUỘC với refund/adjustment/cancel_paid.
- refund/cancel_paid BẮT BUỘC reference_payment_id trỏ payment GỐC cùng order.

payment_status tính lại sau mỗi payment từ TỔNG payments của đơn, ƯU TIÊN:
  1) paid     : total>0 và paid_sum >= total_amount
  2) partial  : 0 < paid_sum < total_amount
  3) refunded : paid_sum <= 0 và có giao dịch refund/cancel_paid
  4) debt     : có debt chưa resolve (có dòng debt, chưa có resolve_debt)
  5) unpaid   : còn lại
"""
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.order import Order
from app.models.payment import Payment
from app.models.shift import Shift
from app.models.user import User
from app.services import order_service

_POSITIVE = {"payment", "resolve_debt", "adjustment"}
_NEGATIVE = {"refund", "cancel_paid"}
_REASON_REQUIRED = {"refund", "adjustment", "cancel_paid"}
_REFERENCE_REQUIRED = {"refund", "cancel_paid"}
_REFUND_TYPES = ("refund", "cancel_paid")


def _signed_amount(transaction_type: str, amount: Decimal) -> Decimal:
    """Áp dấu theo type. debt -> 0; còn lại yêu cầu magnitude > 0."""
    if transaction_type == "debt":
        return Decimal(0)
    if amount is None or amount <= 0:
        raise APIError(422, "INVALID_AMOUNT", "amount phải là số dương (magnitude)")
    mag = amount.quantize(Decimal(1), rounding=ROUND_HALF_UP)
    return -mag if transaction_type in _NEGATIVE else mag


async def _recompute_status(db: AsyncSession, order: Order) -> str:
    row = (
        await db.execute(
            select(
                func.coalesce(func.sum(Payment.amount), Decimal(0)).label("paid"),
                func.count().filter(
                    Payment.transaction_type.in_(_REFUND_TYPES)
                ).label("refunds"),
                func.count().filter(Payment.transaction_type == "debt").label("debts"),
                func.count()
                .filter(Payment.transaction_type == "resolve_debt")
                .label("resolves"),
            ).where(Payment.order_id == order.id)
        )
    ).one()

    paid: Decimal = row.paid
    total: Decimal = order.total_amount

    if total > 0 and paid >= total:
        return "paid"
    if paid > 0 and paid < total:
        return "partial"
    if paid <= 0 and row.refunds > 0:
        return "refunded"
    if row.debts > 0 and row.resolves == 0:
        return "debt"
    return "unpaid"


async def create_payment(
    db: AsyncSession,
    actor: User,
    *,
    order_id: uuid.UUID,
    amount: Decimal,
    payment_method: str,
    transaction_type: str,
    reason: str | None,
    reference_payment_id: uuid.UUID | None,
) -> Payment:
    # Order (tenant + branch scope). 404 nếu không thuộc tenant/branch của actor.
    order = await order_service.get_order(db, actor, order_id)

    # Phải có ca đang OPEN tại branch của đơn.
    shift = await db.scalar(
        select(Shift).where(
            Shift.tenant_id == order.tenant_id,
            Shift.branch_id == order.branch_id,
            Shift.status == "open",
        )
    )
    if shift is None:
        raise APIError(409, "NO_OPEN_SHIFT", "Branch của đơn chưa có ca đang mở")

    # reason bắt buộc.
    if transaction_type in _REASON_REQUIRED and not (reason and reason.strip()):
        raise APIError(422, "REASON_REQUIRED", f"{transaction_type} bắt buộc có reason")

    # Ghi nợ BẮT BUỘC có lý do (Stage 6.12) — code riêng để UI hiện rõ.
    if transaction_type == "debt" and not (reason and reason.strip()):
        raise APIError(422, "DEBT_REASON_REQUIRED", "Ghi nợ bắt buộc có lý do")

    # reference bắt buộc + phải thuộc cùng order.
    if transaction_type in _REFERENCE_REQUIRED:
        if reference_payment_id is None:
            raise APIError(
                422, "REFERENCE_REQUIRED", f"{transaction_type} bắt buộc reference_payment_id"
            )
        ref = await db.scalar(
            select(Payment).where(
                Payment.id == reference_payment_id,
                Payment.tenant_id == order.tenant_id,
            )
        )
        if ref is None or ref.order_id != order.id:
            raise APIError(
                422, "INVALID_REFERENCE", "reference_payment_id không thuộc đơn này"
            )

    signed = _signed_amount(transaction_type, amount)

    payment = Payment(
        tenant_id=order.tenant_id,
        branch_id=order.branch_id,
        order_id=order.id,
        shift_id=shift.id,
        amount=signed,
        payment_method=payment_method,
        transaction_type=transaction_type,
        reason=reason,
        reference_payment_id=reference_payment_id,
        created_by=actor.id,
    )
    db.add(payment)
    await db.flush()

    # Tính lại payment_status từ TỔNG payments của đơn.
    order.payment_status = await _recompute_status(db, order)
    await db.commit()
    return await get_payment(db, actor, payment.id)


async def get_payment(db: AsyncSession, actor: User, payment_id: uuid.UUID) -> Payment:
    payment = await db.scalar(
        select(Payment).where(
            Payment.tenant_id == actor.tenant_id, Payment.id == payment_id
        )
    )
    if payment is None or (
        actor.role != "owner" and payment.branch_id != actor.branch_id
    ):
        raise APIError(404, "PAYMENT_NOT_FOUND", "Không tìm thấy giao dịch")
    return payment


async def list_payments(
    db: AsyncSession,
    actor: User,
    page: Pagination,
    *,
    order_id: uuid.UUID | None = None,
    shift_id: uuid.UUID | None = None,
    branch_id: uuid.UUID | None = None,
    payment_method: str | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[Payment], int]:
    base = select(Payment).where(Payment.tenant_id == actor.tenant_id)
    if actor.role != "owner":
        base = base.where(Payment.branch_id == actor.branch_id)
    elif branch_id is not None:
        base = base.where(Payment.branch_id == branch_id)
    if order_id is not None:
        base = base.where(Payment.order_id == order_id)
    if shift_id is not None:
        base = base.where(Payment.shift_id == shift_id)
    if payment_method is not None:
        base = base.where(Payment.payment_method == payment_method)
    if date_from is not None:
        base = base.where(Payment.created_at >= date_from)
    if date_to is not None:
        base = base.where(Payment.created_at <= date_to)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Payment.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return list(result.scalars().all()), total
