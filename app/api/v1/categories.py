"""Category (danh mục dịch vụ) endpoints. owner/manager ghi; mọi role đọc.

Tenant-scoped. Soft delete qua is_active; chặn xóa danh mục còn dịch vụ active.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.category import (
    CategoryCreate,
    CategoryOut,
    CategoryReorder,
    CategoryUpdate,
)
from app.schemas.common import Page
from app.services import category_service

router = APIRouter(prefix="/categories", tags=["categories"])

Reader = Annotated[User, Depends(require_role("owner", "manager", "staff", "shipper"))]
Writer = Annotated[User, Depends(require_role("owner", "manager"))]


@router.get("", response_model=Page[CategoryOut])
async def list_categories(
    actor: Reader,
    db: DbSession,
    page: PageParams,
    include_inactive: Annotated[bool, Query()] = False,
) -> Page[CategoryOut]:
    items, total = await category_service.list_categories(
        db, actor.tenant_id, page, include_inactive=include_inactive
    )
    return Page[CategoryOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.post("", response_model=CategoryOut, status_code=status.HTTP_201_CREATED)
async def create_category(payload: CategoryCreate, actor: Writer, db: DbSession) -> CategoryOut:
    return await category_service.create_category(db, actor.tenant_id, payload)


# /reorder phải khai báo TRƯỚC /{category_id} để không bị bắt nhầm là path param.
@router.put("/reorder", response_model=list[CategoryOut])
async def reorder_categories(
    payload: CategoryReorder, actor: Writer, db: DbSession
) -> list[CategoryOut]:
    return await category_service.reorder_categories(db, actor.tenant_id, payload.ids)


@router.get("/{category_id}", response_model=CategoryOut)
async def get_category(category_id: uuid.UUID, actor: Reader, db: DbSession) -> CategoryOut:
    return await category_service.get_category(db, actor.tenant_id, category_id)


@router.put("/{category_id}", response_model=CategoryOut)
async def update_category(
    category_id: uuid.UUID, payload: CategoryUpdate, actor: Writer, db: DbSession
) -> CategoryOut:
    return await category_service.update_category(db, actor.tenant_id, category_id, payload)


@router.delete("/{category_id}", response_model=CategoryOut)
async def delete_category(category_id: uuid.UUID, actor: Writer, db: DbSession) -> CategoryOut:
    """Soft delete: is_active=false. Chặn nếu còn dịch vụ active (409 CATEGORY_IN_USE)."""
    return await category_service.soft_delete_category(db, actor.tenant_id, category_id)
