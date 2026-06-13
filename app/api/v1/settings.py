"""Settings endpoints (tenant_settings). Tenant-scoped từ token.

- GET /settings/pos : mọi role đọc cấu hình POS (turnaround) — không lộ secret.
- GET /settings     : owner/manager đọc đầy đủ (gồm telegram).
- PUT /settings     : chỉ owner sửa.
"""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_role
from app.models.user import User
from app.schemas.settings import SettingsOut, SettingsPublic, SettingsUpdate
from app.services import settings_service

router = APIRouter(prefix="/settings", tags=["settings"])

Reader = Annotated[User, Depends(require_role("owner", "manager", "staff", "shipper"))]
Manager = Annotated[User, Depends(require_role("owner", "manager"))]
Owner = Annotated[User, Depends(require_role("owner"))]


@router.get("/pos", response_model=SettingsPublic)
async def pos_settings(actor: Reader, db: DbSession) -> SettingsPublic:
    return await settings_service.get_or_create(db, actor.tenant_id)


@router.get("", response_model=SettingsOut)
async def get_settings(actor: Manager, db: DbSession) -> SettingsOut:
    return await settings_service.get_or_create(db, actor.tenant_id)


@router.put("", response_model=SettingsOut)
async def update_settings(payload: SettingsUpdate, actor: Owner, db: DbSession) -> SettingsOut:
    return await settings_service.update_settings(db, actor.tenant_id, payload)
