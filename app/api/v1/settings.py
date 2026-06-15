"""Settings endpoints (tenant_settings). Tenant-scoped từ token.

- GET /settings/pos : mọi role đọc cấu hình POS (turnaround) — không lộ secret.
- GET /settings     : owner/manager đọc đầy đủ (gồm telegram).
- PUT /settings     : chỉ owner sửa.
"""
from typing import Annotated

from fastapi import APIRouter, Depends, File, UploadFile

from app.api.deps import DbSession, require_role
from app.models.user import User
from app.schemas.settings import (
    ReceiptConfig,
    ReceiptUpdate,
    SettingsOut,
    SettingsPublic,
    SettingsUpdate,
)
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


# ── mẫu phiếu in (Stage 4.1 → song ngữ 2H Stage 5.3) ────────────────────────
@router.get("/receipt", response_model=ReceiptConfig)
async def get_receipt(actor: Reader, db: DbSession) -> ReceiptConfig:
    return await settings_service.get_receipt(db, actor.tenant_id)


@router.put("/receipt", response_model=ReceiptConfig)
async def put_receipt(payload: ReceiptUpdate, actor: Owner, db: DbSession) -> ReceiptConfig:
    return await settings_service.update_receipt(db, actor.tenant_id, payload)


@router.post("/receipt/logo", response_model=ReceiptConfig)
async def upload_logo(
    actor: Owner, db: DbSession, file: Annotated[UploadFile, File()]
) -> ReceiptConfig:
    """Upload logo phiếu (owner). PNG/JPG ~500KB; server resize/optimize, lưu
    file tĩnh và set logo_url. Trả cấu hình phiếu mới."""
    raw = await file.read()
    return await settings_service.save_logo(db, actor.tenant_id, raw, file.content_type)
