"""Customer business logic. Tenant-scoped (customer không gắn branch).

phone KHÔNG unique (khách vãng lai dùng chung số) — tìm theo phone trả về list.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.customer import Customer
from app.schemas.customer import CustomerCreate


async def list_customers(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: Pagination,
    *,
    phone: str | None = None,
) -> tuple[list[Customer], int]:
    base = select(Customer).where(Customer.tenant_id == tenant_id)
    if phone is not None:
        base = base.where(Customer.phone == phone)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Customer.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return list(result.scalars().all()), total


async def get_customer(
    db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
) -> Customer:
    customer = await db.scalar(
        select(Customer).where(
            Customer.tenant_id == tenant_id, Customer.id == customer_id
        )
    )
    if customer is None:
        raise APIError(404, "CUSTOMER_NOT_FOUND", "Không tìm thấy khách hàng")
    return customer


async def create_customer(
    db: AsyncSession, tenant_id: uuid.UUID, data: CustomerCreate
) -> Customer:
    # Tạo nhanh: nếu không có tên thì dùng phone, cuối cùng "Khách lẻ".
    full_name = (data.full_name or "").strip() or data.phone or "Khách lẻ"
    customer = Customer(
        tenant_id=tenant_id,
        full_name=full_name,
        phone=data.phone,
        email=data.email,
        notes=data.notes,
    )
    db.add(customer)
    await db.commit()
    await db.refresh(customer)
    return customer
