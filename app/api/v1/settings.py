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
    ReceiptDefaultStatus,
    ReceiptUpdate,
    SettingsOut,
    SettingsPublic,
    SettingsUpdate,
)
from app.services import admin_default_receipt_service, settings_service

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


# ── mẫu mặc định per-tenant (Stage 5.10) ────────────────────────────────────
@router.get("/receipt/status", response_model=ReceiptDefaultStatus)
async def receipt_status(actor: Manager, db: DbSession) -> ReceiptDefaultStatus:
    return ReceiptDefaultStatus(
        has_tenant_default=await settings_service.has_receipt_default(db, actor.tenant_id)
    )


@router.post("/receipt/save-default", response_model=ReceiptDefaultStatus)
async def save_receipt_default(actor: Owner, db: DbSession) -> ReceiptDefaultStatus:
    """Lưu cấu hình đang dùng làm mẫu mặc định của tenant."""
    await settings_service.save_receipt_default(db, actor.tenant_id)
    return ReceiptDefaultStatus(has_tenant_default=True)


@router.post("/receipt/restore-default", response_model=ReceiptConfig)
async def restore_receipt_default(actor: Owner, db: DbSession) -> ReceiptConfig:
    """⚠️ DEPRECATED (commit lưu-luôn) — FE chuyển sang 2 GET load-only bên dưới. GIỮ cho
    bản FE cũ/cache không gãy. Khôi phục về mẫu mặc định tenant (hoặc mẫu gốc nếu chưa lưu)."""
    return await settings_service.restore_receipt_default(db, actor.tenant_id)


# ── Khôi phục LOAD-ONLY (read-only, KHÔNG commit) — FE nạp vào editor rồi owner tự Lưu ──
@router.get("/receipt/my-default", response_model=ReceiptConfig)
async def get_my_default_receipt(actor: Owner, db: DbSession) -> ReceiptConfig:
    """Mẫu MẶC ĐỊNH của tenant (đã lưu) — load-only. Chưa lưu → 404 NO_DEFAULT."""
    return await settings_service.get_receipt_default(db, actor.tenant_id)


@router.get("/system-default-receipt", response_model=ReceiptConfig)
async def get_system_default_receipt(actor: Owner, db: DbSession) -> ReceiptConfig:
    """Mẫu CHUẨN hệ thống (Super Admin, app_settings) — load-only. Chưa set → mẫu gốc nền
    tảng. app_settings NGOÀI RLS → tenant (GUC=tenant) đọc thẳng được."""
    return await admin_default_receipt_service.get_default_receipt(db)
