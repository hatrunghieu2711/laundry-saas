"""Ẩn/hiện dịch vụ theo chi nhánh (branch_hidden_services). Owner-only ở router.

Mỗi dòng = 1 dịch vụ ẩn ở 1 branch. tenant_id set = actor.tenant_id (cho RLS strict).
Validate branch + service thuộc tenant (get_* raise 404 nếu khác tenant / không có).
"""
import uuid

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branch_hidden_services import BranchHiddenService
from app.services import branch_service, service_service


async def list_hidden(
    db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID
) -> list[uuid.UUID]:
    await branch_service.get_branch(db, tenant_id, branch_id)  # validate (404 nếu khác tenant)
    rows = await db.execute(
        select(BranchHiddenService.service_id).where(
            BranchHiddenService.tenant_id == tenant_id,
            BranchHiddenService.branch_id == branch_id,
        )
    )
    return list(rows.scalars().all())


async def set_visibility(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    branch_id: uuid.UUID,
    service_id: uuid.UUID,
    hidden: bool,
) -> None:
    # Validate cả branch lẫn service thuộc tenant (404 nếu không).
    await branch_service.get_branch(db, tenant_id, branch_id)
    await service_service.get_service(db, tenant_id, service_id)

    if hidden:
        # Idempotent: chỉ thêm nếu chưa có (uq branch_id+service_id cũng chặn trùng).
        exists = await db.scalar(
            select(BranchHiddenService.id).where(
                BranchHiddenService.branch_id == branch_id,
                BranchHiddenService.service_id == service_id,
            )
        )
        if exists is None:
            db.add(
                BranchHiddenService(
                    tenant_id=tenant_id, branch_id=branch_id, service_id=service_id
                )
            )
            await db.commit()
    else:
        await db.execute(
            delete(BranchHiddenService).where(
                BranchHiddenService.branch_id == branch_id,
                BranchHiddenService.service_id == service_id,
            )
        )
        await db.commit()
