"""Admin endpoints (Super Admin) — nhánh MỚI, TÁCH HẲN auth user.

Stage A1: access-token ONLY (KHÔNG cookie/refresh/csrf). Prefix /admin → /api/v1/admin/*.
- POST /admin/auth/login: phone+password → admin access-token (body).
- GET  /admin/me: require_admin → thông tin admin.
Stage A2:
- POST /admin/tenants: tạo tenant mới (tiệm + CN B1 + owner + settings) 1 transaction.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, require_admin
from app.models.admin import Admin
from app.schemas.admin import (
    AdminLoginRequest,
    AdminOut,
    AdminTokenResponse,
    DashboardOut,
    PlanOut,
    ResetOwnerPasswordIn,
    ResetOwnerPasswordOut,
    SetSubscriptionIn,
    SubscriptionOut,
    TenantAdminUpdate,
    TenantAdminUpdateOut,
    TenantCreate,
    TenantCreateOut,
    TenantListItem,
    TenantStatusOut,
)
from app.schemas.settings import ReceiptConfig, ReceiptUpdate
from app.services import (
    admin_auth_service,
    admin_dashboard_service,
    admin_default_receipt_service,
    admin_tenant_service,
)

router = APIRouter(prefix="/admin", tags=["admin"])

CurrentAdminDep = Annotated[Admin, Depends(require_admin())]


@router.post("/auth/login", response_model=AdminTokenResponse)
async def admin_login(payload: AdminLoginRequest, db: DbSession) -> AdminTokenResponse:
    admin = await admin_auth_service.authenticate_admin(db, payload.phone, payload.password)
    session = admin_auth_service.issue_admin_session(admin)
    return AdminTokenResponse(
        access_token=session.access_token,
        expires_in=session.expires_in,
    )


@router.get("/me", response_model=AdminOut)
async def admin_me(current_admin: CurrentAdminDep) -> AdminOut:
    return AdminOut.model_validate(current_admin)


@router.get("/dashboard", response_model=DashboardOut)
async def admin_dashboard(_admin: CurrentAdminDep, db: DbSession) -> DashboardOut:
    """Tổng quan hệ thống (chỉ-đọc): tenant theo status, đơn hôm nay/tháng (giờ VN),
    CN/NV active, tenant cần chú ý (hạn), tenant mới tạo. Đếm xuyên tenant qua loop GUC."""
    return await admin_dashboard_service.get_dashboard(db)


@router.get("/default-receipt", response_model=ReceiptConfig)
async def admin_get_default_receipt(_admin: CurrentAdminDep, db: DbSession):
    """Mẫu in CHUẨN system-wide (tạo tenant mới copy). Chưa set → mẫu gốc nền tảng."""
    return await admin_default_receipt_service.get_default_receipt(db)


@router.put("/default-receipt", response_model=ReceiptConfig)
async def admin_set_default_receipt(payload: ReceiptUpdate, _admin: CurrentAdminDep, db: DbSession):
    """Lưu mẫu chuẩn. Validate + STRIP branch_contact_blocks/logo_url (chỉ giữ phần CHUNG)."""
    return await admin_default_receipt_service.set_default_receipt(db, payload)


@router.post("/tenants", response_model=TenantCreateOut, status_code=status.HTTP_201_CREATED)
async def create_tenant(
    payload: TenantCreate, _admin: CurrentAdminDep, db: DbSession
) -> TenantCreateOut:
    """Admin tạo tenant mới hoàn chỉnh (1 transaction nguyên tử). temp_password hiện 1 lần."""
    result = await admin_tenant_service.create_tenant(db, payload)
    return TenantCreateOut(
        tenant_id=result.tenant_id,
        slug=result.slug,
        owner_phone=result.owner_phone,
        temp_password=result.temp_password,
        branch_code=result.branch_code,
    )


# ── A3: list / detail / sửa / khóa / reset MK owner ─────────────────────────
@router.get("/tenants", response_model=list[TenantListItem])
async def admin_list_tenants(_admin: CurrentAdminDep, db: DbSession) -> list:
    """Danh sách tenant + số liệu nhẹ (CN/nhân viên/đơn gần nhất) qua set_config loop."""
    return await admin_tenant_service.list_tenants_with_stats(db)


@router.get("/tenants/{tenant_id}", response_model=TenantListItem)
async def admin_get_tenant(
    tenant_id: uuid.UUID, _admin: CurrentAdminDep, db: DbSession
):
    return await admin_tenant_service.get_tenant_detail(db, tenant_id)


@router.patch("/tenants/{tenant_id}", response_model=TenantAdminUpdateOut)
async def admin_update_tenant(
    tenant_id: uuid.UUID, payload: TenantAdminUpdate, _admin: CurrentAdminDep, db: DbSession
) -> TenantAdminUpdateOut:
    tenant, slug_changed = await admin_tenant_service.update_tenant_admin(db, tenant_id, payload)
    return TenantAdminUpdateOut(
        id=tenant.id, name=tenant.name, slug=tenant.slug,
        status=tenant.status, slug_changed=slug_changed,
    )


@router.post("/tenants/{tenant_id}/lock", response_model=TenantStatusOut)
async def admin_lock_tenant(
    tenant_id: uuid.UUID, _admin: CurrentAdminDep, db: DbSession
):
    """Khóa tenant (status=suspended) + REVOKE refresh mọi user (khóa hiệu lực ≤30')."""
    return await admin_tenant_service.set_tenant_locked(db, tenant_id, locked=True)


@router.post("/tenants/{tenant_id}/unlock", response_model=TenantStatusOut)
async def admin_unlock_tenant(
    tenant_id: uuid.UUID, _admin: CurrentAdminDep, db: DbSession
):
    return await admin_tenant_service.set_tenant_locked(db, tenant_id, locked=False)


@router.post("/tenants/{tenant_id}/reset-owner-password", response_model=ResetOwnerPasswordOut)
async def admin_reset_owner_password(
    tenant_id: uuid.UUID, payload: ResetOwnerPasswordIn, _admin: CurrentAdminDep, db: DbSession
) -> ResetOwnerPasswordOut:
    """Đặt lại MK owner (sinh ngẫu nhiên) + revoke refresh owner. temp_password HIỆN 1 LẦN."""
    phone, temp_password = await admin_tenant_service.reset_owner_password(
        db, tenant_id, payload.user_id
    )
    return ResetOwnerPasswordOut(owner_phone=phone, temp_password=temp_password)


# ── Plans-1: gói cước ────────────────────────────────────────────────────────
@router.get("/plans", response_model=list[PlanOut])
async def admin_list_plans(_admin: CurrentAdminDep, db: DbSession) -> list:
    return await admin_tenant_service.list_plans(db)


@router.put("/tenants/{tenant_id}/subscription", response_model=SubscriptionOut)
async def admin_set_subscription(
    tenant_id: uuid.UUID, payload: SetSubscriptionIn, _admin: CurrentAdminDep, db: DbSession
):
    """Gán/đổi gói cho tenant (upsert). custom_max_branches override cho ca đặc biệt;
    expires_at = hạn gói (None = vô hạn)."""
    return await admin_tenant_service.set_subscription(
        db, tenant_id, payload.plan_id, payload.custom_max_branches, payload.expires_at
    )
