"""Order endpoints. owner/manager/staff thao tác; mọi thứ tenant-scoped từ token."""
import uuid
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.order import (
    OrderCreate,
    OrderItemIn,
    OrderOut,
    OrderStatusUpdate,
    OrderUpdate,
)
from app.services import order_service

router = APIRouter(prefix="/orders", tags=["orders"])

OrderActor = Annotated[User, Depends(require_role("owner", "manager", "staff"))]


@router.post("", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def create_order(payload: OrderCreate, actor: OrderActor, db: DbSession) -> OrderOut:
    return await order_service.create_order(db, actor, payload)


@router.get("", response_model=Page[OrderOut])
async def list_orders(
    actor: OrderActor,
    db: DbSession,
    page: PageParams,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
    order_status: Annotated[str | None, Query()] = None,
    customer_id: Annotated[uuid.UUID | None, Query()] = None,
    date_from: Annotated[datetime | None, Query(alias="from")] = None,
    date_to: Annotated[datetime | None, Query(alias="to")] = None,
) -> Page[OrderOut]:
    items, total = await order_service.list_orders(
        db, actor, page,
        branch_id=branch_id, order_status=order_status, customer_id=customer_id,
        date_from=date_from, date_to=date_to,
    )
    return Page[OrderOut](items=items, total=total, limit=page.limit, offset=page.offset)


# Khai báo /code/{order_code} TRƯỚC /{order_id} cho rõ ràng.
@router.get("/code/{order_code}", response_model=OrderOut)
async def get_order_by_code(order_code: str, actor: OrderActor, db: DbSession) -> OrderOut:
    return await order_service.get_order_by_code(db, actor, order_code)


@router.get("/{order_id}", response_model=OrderOut)
async def get_order(order_id: uuid.UUID, actor: OrderActor, db: DbSession) -> OrderOut:
    return await order_service.get_order(db, actor, order_id)


@router.put("/{order_id}", response_model=OrderOut)
async def update_order(
    order_id: uuid.UUID, payload: OrderUpdate, actor: OrderActor, db: DbSession
) -> OrderOut:
    return await order_service.update_order(db, actor, order_id, payload)


@router.patch("/{order_id}/status", response_model=OrderOut)
async def change_status(
    order_id: uuid.UUID, payload: OrderStatusUpdate, actor: OrderActor, db: DbSession
) -> OrderOut:
    return await order_service.change_status(db, actor, order_id, payload.order_status)


@router.delete("/{order_id}", response_model=OrderOut)
async def cancel_order(order_id: uuid.UUID, actor: OrderActor, db: DbSession) -> OrderOut:
    return await order_service.cancel_order(db, actor, order_id)


@router.post("/{order_id}/items", response_model=OrderOut, status_code=status.HTTP_201_CREATED)
async def add_item(
    order_id: uuid.UUID, payload: OrderItemIn, actor: OrderActor, db: DbSession
) -> OrderOut:
    return await order_service.add_item(db, actor, order_id, payload)


@router.put("/{order_id}/items/{item_id}", response_model=OrderOut)
async def update_item(
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    payload: OrderItemIn,
    actor: OrderActor,
    db: DbSession,
) -> OrderOut:
    return await order_service.update_item(db, actor, order_id, item_id, payload)


@router.delete("/{order_id}/items/{item_id}", response_model=OrderOut)
async def delete_item(
    order_id: uuid.UUID, item_id: uuid.UUID, actor: OrderActor, db: DbSession
) -> OrderOut:
    return await order_service.delete_item(db, actor, order_id, item_id)
