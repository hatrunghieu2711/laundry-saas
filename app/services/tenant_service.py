"""Tenant business logic. Router chỉ kiểm tra tenant_id (từ token) == của mình."""
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.tenant import Tenant
from app.schemas.tenant import TenantUpdate


async def get_tenant(db: AsyncSession, tenant_id: uuid.UUID) -> Tenant:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise APIError(404, "TENANT_NOT_FOUND", "Không tìm thấy tenant")
    return tenant


async def get_tenant_by_slug(db: AsyncSession, slug: str) -> Tenant | None:
    """Tra tenant theo slug (mã cửa hàng) — tái dùng unique index trên slug.

    Chuẩn hóa lowercase + trim trước khi query để khớp index, tránh lệch
    hoa/thường/space. Trả None nếu rỗng hoặc không tìm thấy (caller quyết định
    lỗi — login trả 401 generic, KHÔNG lộ 'tenant không tồn tại')."""
    normalized = slug.strip().lower()
    if not normalized:
        return None
    result = await db.execute(select(Tenant).where(Tenant.slug == normalized))
    return result.scalar_one_or_none()


async def update_tenant(
    db: AsyncSession, tenant_id: uuid.UUID, data: TenantUpdate
) -> Tenant:
    tenant = await get_tenant(db, tenant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(tenant, field, value)
    await db.commit()
    await db.refresh(tenant)
    return tenant
