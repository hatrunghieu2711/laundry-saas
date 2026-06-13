"""Shift endpoints: mở/đóng ca + reconciliation.

- owner/manager/staff được mở/đóng ca (owner phải chỉ định branch_id).
- Không có endpoint reopen: ca đã closed là bất biến.
"""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.shift import ShiftClose, ShiftOpen, ShiftOut
from app.services import shift_service

router = APIRouter(prefix="/shifts", tags=["shifts"])

# Shipper (COD) sẽ thêm ở Stage 6; hiện owner/manager/staff thao tác ca.
ShiftActor = Annotated[User, Depends(require_role("owner", "manager", "staff"))]


@router.post("/open", response_model=ShiftOut, status_code=status.HTTP_201_CREATED)
async def open_shift(payload: ShiftOpen, actor: ShiftActor, db: DbSession) -> ShiftOut:
    return await shift_service.open_shift(db, actor, payload.opening_cash, payload.branch_id)


@router.get("/current", response_model=ShiftOut)
async def current_shift(
    actor: ShiftActor,
    db: DbSession,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> ShiftOut:
    return await shift_service.get_current_shift(db, actor, branch_id)


@router.get("", response_model=Page[ShiftOut])
async def list_shifts(
    actor: ShiftActor,
    db: DbSession,
    page: PageParams,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> Page[ShiftOut]:
    items, total = await shift_service.list_shifts(
        db, actor, page, branch_id=branch_id, date_from=date_from, date_to=date_to
    )
    return Page[ShiftOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{shift_id}", response_model=ShiftOut)
async def get_shift(shift_id: uuid.UUID, actor: ShiftActor, db: DbSession) -> ShiftOut:
    return await shift_service.get_shift(db, actor, shift_id)


@router.post("/{shift_id}/close", response_model=ShiftOut)
async def close_shift(
    shift_id: uuid.UUID, payload: ShiftClose, actor: ShiftActor, db: DbSession
) -> ShiftOut:
    return await shift_service.close_shift(db, actor, shift_id, payload.closing_cash_actual)
