"""Payment endpoints. INSERT only; tenant-scoped từ token.

branch/tenant/shift của payment do service suy từ order + ca đang mở.
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.payment import PaymentCreate, PaymentOut, RefundCreate
from app.services import payment_service

router = APIRouter(prefix="/payments", tags=["payments"])

PaymentActor = Annotated[User, Depends(require_role("owner", "manager", "staff"))]


@router.post("", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaymentCreate, actor: PaymentActor, db: DbSession
) -> PaymentOut:
    return await payment_service.create_payment(
        db, actor,
        order_id=payload.order_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
        transaction_type=payload.transaction_type,
        reason=payload.reason,
        reference_payment_id=payload.reference_payment_id,
    )


@router.post("/refund", response_model=PaymentOut, status_code=status.HTTP_201_CREATED)
async def create_refund(
    payload: RefundCreate, actor: PaymentActor, db: DbSession
) -> PaymentOut:
    return await payment_service.create_payment(
        db, actor,
        order_id=payload.order_id,
        amount=payload.amount,
        payment_method=payload.payment_method,
        transaction_type="refund",
        reason=payload.reason,
        reference_payment_id=payload.reference_payment_id,
    )


@router.get("", response_model=Page[PaymentOut])
async def list_payments(
    actor: PaymentActor,
    db: DbSession,
    page: PageParams,
    order_id: Annotated[uuid.UUID | None, Query()] = None,
    shift_id: Annotated[uuid.UUID | None, Query()] = None,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
    payment_method: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> Page[PaymentOut]:
    items, total = await payment_service.list_payments(
        db, actor, page,
        order_id=order_id, shift_id=shift_id, branch_id=branch_id,
        payment_method=payment_method, date_from=date_from, date_to=date_to,
    )
    return Page[PaymentOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{payment_id}", response_model=PaymentOut)
async def get_payment(
    payment_id: uuid.UUID, actor: PaymentActor, db: DbSession
) -> PaymentOut:
    return await payment_service.get_payment(db, actor, payment_id)
