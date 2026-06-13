"""Branch endpoints.

- owner: tạo / sửa / soft-delete.
- manager: chỉ đọc (mọi branch trong tenant).
- staff/shipper: chỉ đọc branch của mình.
"""
import uuid

from fastapi import APIRouter, Depends, status

from app.api.deps import CurrentUser, DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.branch import BranchCreate, BranchOut, BranchUpdate
from app.schemas.common import Page
from app.services import branch_service

router = APIRouter(prefix="/branches", tags=["branches"])

_BRANCH_SCOPED = ("staff", "shipper")


def _only_branch_for(user: User) -> uuid.UUID | None:
    """staff/shipper bị giới hạn về branch của mình; owner/manager thấy tất cả."""
    return user.branch_id if user.role in _BRANCH_SCOPED else None


@router.get("", response_model=Page[BranchOut])
async def list_branches(
    current_user: CurrentUser, db: DbSession, page: PageParams
) -> Page[BranchOut]:
    items, total = await branch_service.list_branches(
        db, current_user.tenant_id, page, only_branch_id=_only_branch_for(current_user)
    )
    return Page[BranchOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{branch_id}", response_model=BranchOut)
async def get_branch(
    branch_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> BranchOut:
    return await branch_service.get_branch(
        db, current_user.tenant_id, branch_id, only_branch_id=_only_branch_for(current_user)
    )


@router.post(
    "",
    response_model=BranchOut,
    status_code=status.HTTP_201_CREATED,
    dependencies=[Depends(require_role("owner"))],
)
async def create_branch(
    payload: BranchCreate, current_user: CurrentUser, db: DbSession
) -> BranchOut:
    return await branch_service.create_branch(db, current_user.tenant_id, payload)


@router.patch(
    "/{branch_id}",
    response_model=BranchOut,
    dependencies=[Depends(require_role("owner"))],
)
async def update_branch(
    branch_id: uuid.UUID,
    payload: BranchUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> BranchOut:
    return await branch_service.update_branch(db, current_user.tenant_id, branch_id, payload)


@router.delete(
    "/{branch_id}",
    response_model=BranchOut,
    dependencies=[Depends(require_role("owner"))],
)
async def delete_branch(
    branch_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> BranchOut:
    return await branch_service.soft_delete_branch(db, current_user.tenant_id, branch_id)
