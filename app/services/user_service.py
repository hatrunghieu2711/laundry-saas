"""User business logic + phân quyền chi tiết.

Phân quyền (CLAUDE.md QUY TẮC MULTI-TENANT + yêu cầu Stage 1):
- owner: tạo/sửa/soft-delete MỌI user trong tenant.
- manager: tạo/sửa staff+shipper TRONG branch của mình.
- KHÔNG ai sửa được role của một owner.
- Mọi query filter tenant_id (từ token).
"""
import uuid

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.core.security import hash_password
from app.models.user import User
from app.schemas.user import UserCreate, UserUpdate

_MANAGER_MANAGEABLE = ("staff", "shipper")


def _forbid(message: str) -> None:
    raise APIError(403, "FORBIDDEN", message)


def _assert_can_create(actor: User, role: str) -> None:
    if actor.role == "owner":
        return
    if actor.role == "manager":
        if role not in _MANAGER_MANAGEABLE:
            _forbid("Manager chỉ được tạo staff hoặc shipper")
        return
    _forbid("Bạn không có quyền tạo người dùng")


def _assert_can_manage(actor: User, target: User) -> None:
    """Quyền sửa/xóa target. owner: mọi user; manager: staff/shipper cùng branch."""
    if actor.role == "owner":
        return
    if actor.role == "manager":
        if target.role in _MANAGER_MANAGEABLE and target.branch_id == actor.branch_id:
            return
    _forbid("Bạn không có quyền với người dùng này")


async def list_users(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: Pagination,
    *,
    branch_id: uuid.UUID | None = None,
) -> tuple[list[User], int]:
    """branch_id: giới hạn về 1 branch (manager chỉ thấy user branch mình)."""
    base = select(User).where(User.tenant_id == tenant_id)
    if branch_id is not None:
        base = base.where(User.branch_id == branch_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(User.created_at).limit(page.limit).offset(page.offset)
    )
    return list(result.scalars().all()), total


async def get_user(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID
) -> User:
    stmt = select(User).where(User.tenant_id == tenant_id, User.id == user_id)
    user = (await db.execute(stmt)).scalar_one_or_none()
    if user is None:
        raise APIError(404, "USER_NOT_FOUND", "Không tìm thấy người dùng")
    return user


async def create_user(db: AsyncSession, actor: User, data: UserCreate) -> User:
    _assert_can_create(actor, data.role)
    # Manager bị ép về branch của mình; không tin branch_id từ body.
    branch_id = actor.branch_id if actor.role == "manager" else data.branch_id
    user = User(
        tenant_id=actor.tenant_id,
        branch_id=branch_id,
        role=data.role,
        full_name=data.full_name,
        phone=data.phone,
        email=data.email,
        password_hash=hash_password(data.password),
        status="active",
    )
    db.add(user)
    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise APIError(
            409, "PHONE_EXISTS", "Số điện thoại đã tồn tại trong tenant"
        ) from exc
    await db.refresh(user)
    return user


async def update_user(
    db: AsyncSession, actor: User, user_id: uuid.UUID, data: UserUpdate
) -> User:
    target = await get_user(db, actor.tenant_id, user_id)
    _assert_can_manage(actor, target)
    changes = data.model_dump(exclude_unset=True)

    if "role" in changes:
        # KHÔNG ai sửa được role của owner.
        if target.role == "owner":
            _forbid("Không được sửa vai trò của owner")
        if actor.role == "manager" and changes["role"] not in _MANAGER_MANAGEABLE:
            _forbid("Manager chỉ gán được vai trò staff hoặc shipper")
    if actor.role == "manager" and "branch_id" in changes:
        if changes["branch_id"] != actor.branch_id:
            _forbid("Manager không thể chuyển người dùng sang branch khác")

    password = changes.pop("password", None)
    if password:
        target.password_hash = hash_password(password)
    for field, value in changes.items():
        setattr(target, field, value)

    try:
        await db.commit()
    except IntegrityError as exc:
        await db.rollback()
        raise APIError(
            409, "PHONE_EXISTS", "Số điện thoại đã tồn tại trong tenant"
        ) from exc
    await db.refresh(target)
    return target


async def soft_delete_user(
    db: AsyncSession, actor: User, user_id: uuid.UUID
) -> User:
    target = await get_user(db, actor.tenant_id, user_id)
    _assert_can_manage(actor, target)
    if target.role == "owner":
        _forbid("Không được xóa owner")
    if target.id == actor.id:
        raise APIError(409, "CANNOT_DELETE_SELF", "Không thể tự xóa chính mình")
    target.status = "inactive"
    await db.commit()
    await db.refresh(target)
    return target
