"""Tenant endpoints. Chỉ đọc/sửa tenant CỦA MÌNH (tenant_id từ token).

POST /tenants chưa mở — tạo tenant mới là việc super admin (Stage 7) -> 403.
"""
import uuid

from fastapi import APIRouter, Depends

from app.api.deps import CurrentUser, DbSession, require_role
from app.core.errors import APIError
from app.models.user import User
from app.schemas.tenant import TenantOut, TenantUpdate
from app.services import tenant_service

router = APIRouter(prefix="/tenants", tags=["tenants"])


def _ensure_own_tenant(user: User, tenant_id: uuid.UUID) -> None:
    if user.tenant_id != tenant_id:
        raise APIError(403, "FORBIDDEN", "Không có quyền truy cập tenant khác")


@router.post("", status_code=403)
async def create_tenant() -> None:
    raise APIError(
        403, "FEATURE_NOT_AVAILABLE", "Tạo tenant mới là chức năng super admin (Stage 7)"
    )


@router.get("/{tenant_id}", response_model=TenantOut)
async def get_one(
    tenant_id: uuid.UUID, current_user: CurrentUser, db: DbSession
) -> TenantOut:
    _ensure_own_tenant(current_user, tenant_id)
    return await tenant_service.get_tenant(db, tenant_id)


@router.patch(
    "/{tenant_id}",
    response_model=TenantOut,
    dependencies=[Depends(require_role("owner"))],
)
async def update_one(
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    current_user: CurrentUser,
    db: DbSession,
) -> TenantOut:
    _ensure_own_tenant(current_user, tenant_id)
    return await tenant_service.update_tenant(db, tenant_id, payload)
