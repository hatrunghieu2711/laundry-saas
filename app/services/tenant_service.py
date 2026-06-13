"""Tenant business logic. Router chỉ kiểm tra tenant_id (từ token) == của mình."""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.tenant import Tenant
from app.schemas.tenant import TenantUpdate


async def get_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise APIError(404, "TENANT_NOT_FOUND", "Không tìm thấy tenant")
    return tenant


async def update_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, data: TenantUpdate
) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    await db.commit()
    await db.refresh(tenant)
    return tenant
