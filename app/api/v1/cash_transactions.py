"""Cash transactions (sổ quỹ thu-chi) endpoints — Stage 4.2.

INSERT only; tenant-scoped từ token. shift_id/tenant_id do service suy từ ca
đang mở. Không có UPDATE/DELETE (immutable, sửa sai = ghi giao dịch đối ứng).
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.cash_transaction import CashTransactionCreate, CashTransactionOut
from app.schemas.common import Page
from app.services import cash_transaction_service

router = APIRouter(prefix="/cash-transactions", tags=["cash-transactions"])

CashActor = Annotated[User, Depends(require_role("owner", "manager", "staff"))]


@router.post("", response_model=CashTransactionOut, status_code=status.HTTP_201_CREATED)
async def create_cash_transaction(
    payload: CashTransactionCreate, actor: CashActor, db: DbSession
) -> CashTransactionOut:
    return await cash_transaction_service.create_cash_transaction(
        db, actor,
        type=payload.type,
        amount=payload.amount,
        category=payload.category,
        note=payload.note,
        payment_method=payload.payment_method,
        branch_id=payload.branch_id,
    )


@router.get("", response_model=Page[CashTransactionOut])
async def list_cash_transactions(
    actor: CashActor,
    db: DbSession,
    page: PageParams,
    shift_id: Annotated[uuid.UUID | None, Query()] = None,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
    type: Annotated[str | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> Page[CashTransactionOut]:
    items, total = await cash_transaction_service.list_cash_transactions(
        db, actor, page,
        shift_id=shift_id, branch_id=branch_id, type=type,
        date_from=date_from, date_to=date_to,
    )
    return Page[CashTransactionOut](
        items=items, total=total, limit=page.limit, offset=page.offset
    )


@router.get("/{ct_id}", response_model=CashTransactionOut)
async def get_cash_transaction(
    ct_id: uuid.UUID, actor: CashActor, db: DbSession
) -> CashTransactionOut:
    return await cash_transaction_service.get_cash_transaction(db, actor, ct_id)
