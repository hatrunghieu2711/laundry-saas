"""User (nhân sự) endpoints. Phân quyền chi tiết trong user_service.

- owner: tạo/sửa/soft-delete mọi user trong tenant.
- manager: tạo/sửa staff+shipper trong branch của mình.
- staff/shipper: không quản lý user.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.user import (
    ResetPasswordIn,
    UserCreate,
    UserOut,
    UserStatusUpdate,
    UserUpdate,
)
from app.services import user_service

router = APIRouter(prefix="/users", tags=["users"])

# Chỉ owner & manager chạm tới khu vực quản lý user.
ManagerOrOwner = Annotated[User, Depends(require_role("owner", "manager"))]


def _list_scope(actor: User) -> uuid.UUID | None:
    """Manager chỉ thấy user branch mình; owner thấy toàn tenant."""
    return actor.branch_id if actor.role == "manager" else None


@router.get("", response_model=Page[UserOut])
async def list_users(
    actor: ManagerOrOwner, db: DbSession, page: PageParams
) -> Page[UserOut]:
    items, total = await user_service.list_users(
        db, actor.tenant_id, page, branch_id=_list_scope(actor)
    )
    return Page[UserOut](items=items, total=total, limit=page.limit, offset=page.offset)


@router.get("/{user_id}", response_model=UserOut)
async def get_user(
    user_id: uuid.UUID, actor: ManagerOrOwner, db: DbSession
) -> UserOut:
    return await user_service.get_user(db, actor.tenant_id, user_id)


@router.post(
    "", response_model=UserOut, status_code=status.HTTP_201_CREATED
)
async def create_user(
    payload: UserCreate, actor: ManagerOrOwner, db: DbSession
) -> UserOut:
    return await user_service.create_user(db, actor, payload)


@router.patch("/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID,
    payload: UserUpdate,
    actor: ManagerOrOwner,
    db: DbSession,
) -> UserOut:
    return await user_service.update_user(db, actor, user_id, payload)


@router.post("/{user_id}/reset-password", response_model=UserOut)
async def reset_password(
    user_id: uuid.UUID,
    payload: ResetPasswordIn,
    actor: ManagerOrOwner,
    db: DbSession,
) -> UserOut:
    return await user_service.reset_password(db, actor, user_id, payload.password)


@router.patch("/{user_id}/status", response_model=UserOut)
async def set_status(
    user_id: uuid.UUID,
    payload: UserStatusUpdate,
    actor: ManagerOrOwner,
    db: DbSession,
) -> UserOut:
    """Khóa (suspended) / mở (active) tài khoản. Không tự khóa mình."""
    return await user_service.set_status(db, actor, user_id, payload.status)


@router.delete("/{user_id}", response_model=UserOut)
async def delete_user(
    user_id: uuid.UUID, actor: ManagerOrOwner, db: DbSession
) -> UserOut:
    return await user_service.soft_delete_user(db, actor, user_id)
