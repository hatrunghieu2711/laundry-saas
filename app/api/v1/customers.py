"""Customer endpoints. owner/manager/staff; tenant-scoped từ token."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.customer import CustomerCreate, CustomerOut
from app.services import customer_service

router = APIRouter(prefix="/customers", tags=["customers"])

CustomerActor = Annotated[User, Depends(require_role("owner", "manager", "staff"))]


@router.get("", response_model=Page[CustomerOut])
async def list_customers(
    actor: CustomerActor,
    db: DbSession,
    page: PageParams,
    phone: Annotated[str | None, Query()] = None,
) -> Page[CustomerOut]:
    items, total = await customer_service.list_customers(
        db, actor.tenant_id, page, phone=phone
    )
    return Page[CustomerOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=CustomerOut, status_code=status.HTTP_201_CREATED)
async def create_customer(
    payload: CustomerCreate, actor: CustomerActor, db: DbSession
) -> CustomerOut:
    return await customer_service.create_customer(db, actor.tenant_id, payload)


@router.get("/{customer_id}", response_model=CustomerOut)
async def get_customer(
    customer_id: uuid.UUID, actor: CustomerActor, db: DbSession
) -> CustomerOut:
    return await customer_service.get_customer(db, actor.tenant_id, customer_id)
