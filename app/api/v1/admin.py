"""Admin endpoints (Super Admin) — nhánh MỚI, TÁCH HẲN auth user.

Stage A1: access-token ONLY (KHÔNG cookie/refresh/csrf). Prefix /admin → /api/v1/admin/*.
- POST /admin/auth/login: phone+password → admin access-token (body).
- GET  /admin/me: require_admin → thông tin admin.
"""
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_admin
from app.models.admin import Admin
from app.schemas.admin import AdminLoginRequest, AdminOut, AdminTokenResponse
from app.services import admin_auth_service

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
