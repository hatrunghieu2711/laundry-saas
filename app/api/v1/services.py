"""Service (bảng giá) endpoints. owner/manager ghi; mọi role đọc. Tenant-scoped."""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.service import ServiceCreate, ServiceOut, ServiceUpdate
from app.services import service_service

router = APIRouter(prefix="/services", tags=["services"])

Reader = Annotated[User, Depends(require_role("owner", "manager", "staff", "shipper"))]
Writer = Annotated[User, Depends(require_role("owner", "manager"))]


@router.get("", response_model=Page[ServiceOut])
async def list_services(
    actor: Reader,
    db: DbSession,
    page: PageParams,
    include_inactive: Annotated[bool, Query()] = False,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> Page[ServiceOut]:
    # branch_id (tùy chọn): loại dịch vụ bị ẩn ở CN đó (màn tạo đơn). Không có → trả hết.
    items, total = await service_service.list_services(
        db, actor.tenant_id, page,
        include_inactive=include_inactive, visible_in_branch=branch_id,
    )
    return Page[ServiceOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=ServiceOut, status_code=status.HTTP_201_CREATED)
async def create_service(payload: ServiceCreate, actor: Writer, db: DbSession) -> ServiceOut:
    return await service_service.create_service(db, actor.tenant_id, payload)


@router.get("/{service_id}", response_model=ServiceOut)
async def get_service(service_id: uuid.UUID, actor: Reader, db: DbSession) -> ServiceOut:
    return await service_service.get_service(db, actor.tenant_id, service_id)


@router.put("/{service_id}", response_model=ServiceOut)
async def update_service(
    service_id: uuid.UUID, payload: ServiceUpdate, actor: Writer, db: DbSession
) -> ServiceOut:
    return await service_service.update_service(db, actor.tenant_id, service_id, payload)


@router.delete("/{service_id}", response_model=ServiceOut)
async def delete_service(service_id: uuid.UUID, actor: Writer, db: DbSession) -> ServiceOut:
    """Soft delete: is_active=false (giữ lịch sử, đơn cũ vẫn truy nguồn được)."""
    return await service_service.soft_delete_service(db, actor.tenant_id, service_id)
