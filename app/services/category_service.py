"""CRUD danh mục dịch vụ (categories) — Stage 4.3. Tenant-scoped.

owner/manager ghi (tạo/sửa/xóa-soft/sắp thứ tự); mọi role đọc. Soft delete qua
is_active. Chặn xóa danh mục còn dịch vụ ĐANG DÙNG (active) — báo còn N dịch vụ.
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.category import Category
from app.models.service import Service
from app.schemas.category import CategoryCreate, CategoryUpdate


async def list_categories(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: Pagination,
    *,
    include_inactive: bool = False,
) -> tuple[list[Category], int]:
    base = select(Category).where(Category.tenant_id == tenant_id)
    if not include_inactive:
        base = base.where(Category.is_active.is_(True))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Category.display_order, Category.created_at)
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(result.scalars().all()), total


async def get_category(
    db: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
) -> Category:
    category = await db.scalar(
        select(Category).where(
            Category.tenant_id == tenant_id, Category.id == category_id
        )
    )
    if category is None:
        raise APIError(404, "CATEGORY_NOT_FOUND", "Không tìm thấy danh mục")
    return category


async def get_active_category(
    db: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
) -> Category:
    """Dùng khi gán cho dịch vụ: chỉ chấp nhận danh mục thuộc tenant + còn active."""
    category = await db.scalar(
        select(Category).where(
            Category.tenant_id == tenant_id,
            Category.id == category_id,
            Category.is_active.is_(True),
        )
    )
    if category is None:
        raise APIError(422, "INVALID_CATEGORY", "Danh mục không hợp lệ hoặc đã ẩn")
    return category


async def create_category(
    db: AsyncSession, tenant_id: uuid.UUID, data: CategoryCreate
) -> Category:
    category = Category(
        tenant_id=tenant_id,
        name=data.name.strip(),
        icon=data.icon,
        display_order=data.display_order,
        is_active=True,
    )
    db.add(category)
    await db.commit()
    return await get_category(db, tenant_id, category.id)


async def update_category(
    db: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID, data: CategoryUpdate
) -> Category:
    category = await get_category(db, tenant_id, category_id)
    changes = data.model_dump(exclude_unset=True)
    if "name" in changes and changes["name"]:
        changes["name"] = changes["name"].strip()
    for field, value in changes.items():
        setattr(category, field, value)
    await db.commit()
    return await get_category(db, tenant_id, category_id)


async def reorder_categories(
    db: AsyncSession, tenant_id: uuid.UUID, ids: list[uuid.UUID]
) -> list[Category]:
    """Gán display_order = vị trí trong danh sách. Bỏ qua id không thuộc tenant."""
    rows = (
        await db.execute(
            select(Category).where(
                Category.tenant_id == tenant_id, Category.id.in_(ids)
            )
        )
    ).scalars().all()
    by_id = {c.id: c for c in rows}
    for order, cid in enumerate(ids):
        cat = by_id.get(cid)
        if cat is not None:
            cat.display_order = order
    await db.commit()
    page = Pagination(limit=200, offset=0)
    items, _ = await list_categories(db, tenant_id, page, include_inactive=True)
    return items


async def soft_delete_category(
    db: AsyncSession, tenant_id: uuid.UUID, category_id: uuid.UUID
) -> Category:
    category = await get_category(db, tenant_id, category_id)
    # Chặn xóa nếu còn dịch vụ ACTIVE đang dùng danh mục này.
    in_use = await db.scalar(
        select(func.count())
        .select_from(Service)
        .where(
            Service.tenant_id == tenant_id,
            Service.category_id == category_id,
            Service.is_active.is_(True),
        )
    ) or 0
    if in_use > 0:
        raise APIError(
            409, "CATEGORY_IN_USE",
            f"Còn {in_use} dịch vụ trong danh mục này — chuyển hoặc ẩn dịch vụ trước khi xóa",
        )
    category.is_active = False
    await db.commit()
    return await get_category(db, tenant_id, category_id)
