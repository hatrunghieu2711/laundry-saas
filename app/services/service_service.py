"""CRUD bảng giá dịch vụ (services + service_tiers). Tenant-scoped.

owner/manager ghi (tạo/sửa/xóa-soft); mọi role đọc. Soft delete qua is_active.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.service import Service, ServiceTier
from app.schemas.service import ServiceCreate, ServiceTierIn, ServiceUpdate


def _make_tiers(tiers: list[ServiceTierIn]) -> list[ServiceTier]:
    return [
        ServiceTier(
            label=t.label,
            max_value=t.max_value,
            price=t.price,
            per_unit=t.per_unit,
            display_order=t.display_order,
        )
        for t in tiers
    ]


async def list_services(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: Pagination,
    *,
    include_inactive: bool = False,
) -> tuple[list[Service], int]:
    base = select(Service).where(Service.tenant_id == tenant_id)
    if not include_inactive:
        base = base.where(Service.is_active.is_(True))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Service.display_order, Service.created_at)
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(result.scalars().all()), total


async def get_service(
    db: AsyncSession, tenant_id: uuid.UUID, service_id: uuid.UUID
) -> Service:
    service = await db.scalar(
        select(Service).where(
            Service.tenant_id == tenant_id, Service.id == service_id
        )
    )
    if service is None:
        raise APIError(404, "SERVICE_NOT_FOUND", "Không tìm thấy dịch vụ")
    return service


async def get_active_service(
    db: AsyncSession, tenant_id: uuid.UUID, service_id: uuid.UUID
) -> Service:
    """Dùng khi tạo đơn: chỉ chấp nhận dịch vụ còn active."""
    service = await get_service(db, tenant_id, service_id)
    if not service.is_active:
        raise APIError(422, "SERVICE_INACTIVE", "Dịch vụ đã ngừng, không thể chọn")
    return service


async def create_service(
    db: AsyncSession, tenant_id: uuid.UUID, data: ServiceCreate
) -> Service:
    service = Service(
        tenant_id=tenant_id,
        name=data.name,
        unit=data.unit,
        unit_price=data.unit_price,
        pricing_type=data.pricing_type,
        display_order=data.display_order,
        category=data.category,
        is_favorite=data.is_favorite,
        is_active=True,
        tiers=_make_tiers(data.tiers),
    )
    db.add(service)
    await db.commit()
    return await get_service(db, tenant_id, service.id)


async def update_service(
    db: AsyncSession, tenant_id: uuid.UUID, service_id: uuid.UUID, data: ServiceUpdate
) -> Service:
    service = await get_service(db, tenant_id, service_id)
    changes = data.model_dump(exclude_unset=True)
    tiers = changes.pop("tiers", None)
    for field, value in changes.items():
        setattr(service, field, value)
    if tiers is not None:
        # Thay toàn bộ bậc giá (cascade delete-orphan xóa bậc cũ).
        service.tiers = _make_tiers(data.tiers)
    await db.commit()
    return await get_service(db, tenant_id, service_id)


async def soft_delete_service(
    db: AsyncSession, tenant_id: uuid.UUID, service_id: uuid.UUID
) -> Service:
    service = await get_service(db, tenant_id, service_id)
    service.is_active = False
    await db.commit()
    return await get_service(db, tenant_id, service_id)
