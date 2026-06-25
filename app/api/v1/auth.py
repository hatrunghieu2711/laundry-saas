"""Auth endpoints: login / refresh / logout / me.

- access_token: JWT trong body (client giữ ở memory).
- refresh_token: cookie httpOnly + Secure + SameSite=Strict (path hẹp /api/v1/auth).
- CSRF double-submit: csrf_token vừa ở body/cookie, client gửi lại qua X-CSRF-Token.
"""
from typing import Annotated

from fastapi import APIRouter, Cookie, Header, Response, status

from app.api.deps import CurrentUser, DbSession
from app.core.config import get_settings
from app.core.errors import APIError
from app.models.tenant import Tenant
from app.schemas.auth import (
    ChangePasswordRequest,
    LoginRequest,
    TokenResponse,
    UserOut,
)
from app.services import auth_service, branch_service
from app.services.auth_service import IssuedSession

router = APIRouter(prefix="/auth", tags=["auth"])
_settings = get_settings()


def _set_session_cookies(response: Response, session: IssuedSession) -> None:
    """Set refresh cookie (httpOnly) + csrf cookie (đọc được bởi JS)."""
    refresh_max_age = _settings.jwt_refresh_ttl_days * 24 * 3600
    response.set_cookie(
        key=_settings.refresh_cookie_name,
        value=session.refresh_token_raw,
        max_age=refresh_max_age,
        httponly=True,
        secure=_settings.cookie_secure,
        samesite=_settings.cookie_samesite,
        path=_settings.auth_cookie_path,
    )
    # CSRF cookie KHÔNG httpOnly để JS đọc, đặt path="/" cho SPA đọc được.
    response.set_cookie(
        key=_settings.csrf_cookie_name,
        value=session.csrf_token,
        max_age=refresh_max_age,
        httponly=False,
        secure=_settings.cookie_secure,
        samesite=_settings.cookie_samesite,
        path="/",
    )


def _clear_session_cookies(response: Response) -> None:
    response.delete_cookie(_settings.refresh_cookie_name, path=_settings.auth_cookie_path)
    response.delete_cookie(_settings.csrf_cookie_name, path="/")


def _token_response(session: IssuedSession) -> TokenResponse:
    return TokenResponse(
        access_token=session.access_token,
        expires_in=session.expires_in,
        csrf_token=session.csrf_token,
    )


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest, response: Response, db: DbSession) -> TokenResponse:
    user = await auth_service.authenticate(db, payload.phone, payload.password, payload.slug)
    session = await auth_service.issue_session(db, user)
    _set_session_cookies(response, session)
    return _token_response(session)


@router.post("/refresh", response_model=TokenResponse)
async def refresh(
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=_settings.refresh_cookie_name)] = None,
    csrf_cookie: Annotated[str | None, Cookie(alias=_settings.csrf_cookie_name)] = None,
    x_csrf_token: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> TokenResponse:
    if not refresh_token:
        raise APIError(401, "INVALID_REFRESH_TOKEN", "Thiếu refresh token")
    # CSRF double-submit: header phải khớp cookie.
    if not x_csrf_token or not csrf_cookie or x_csrf_token != csrf_cookie:
        raise APIError(403, "CSRF_FAILED", "CSRF token không hợp lệ")

    session = await auth_service.rotate_session(db, refresh_token)
    _set_session_cookies(response, session)
    return _token_response(session)


@router.post("/logout", status_code=status.HTTP_200_OK)
async def logout(
    response: Response,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=_settings.refresh_cookie_name)] = None,
) -> dict[str, bool]:
    await auth_service.revoke_session(db, refresh_token)
    _clear_session_cookies(response)
    return {"success": True}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: CurrentUser,
    db: DbSession,
    refresh_token: Annotated[str | None, Cookie(alias=_settings.refresh_cookie_name)] = None,
) -> dict[str, bool]:
    """Tự đổi MK (Bearer auth). Đọc refresh cookie để CHỪA phiên hiện tại khi đăng
    xuất thiết bị khác (cookie path /api/v1/auth gồm cả route này)."""
    await auth_service.change_password(
        db,
        current_user,
        payload.current_password,
        payload.new_password,
        refresh_token,
    )
    return {"success": True}


@router.get("/me", response_model=UserOut)
async def me(current_user: CurrentUser, db: DbSession) -> UserOut:
    """Thông tin user + TÊN TIỆM (tenant.name) cho FE hiển thị.

    tenants NGOÀI RLS → đọc được dù GUC = tenant của user. Gán transient
    tenant_name lên current_user rồi validate (cùng pattern branch_name ở list_users).
    """
    tenant = await db.get(Tenant, current_user.tenant_id)
    current_user.tenant_name = tenant.name if tenant is not None else None
    # CÙNG query (không round-trip thêm) — slug cho QR bill (track/{slug}/{order_code}).
    current_user.tenant_slug = tenant.slug if tenant is not None else None
    # Hạn GÓI cho banner POS (1 query; GUC=tenant đã set cho strict subscriptions).
    # Tái dùng subscription_info (Stage 1) → status/expires_at/days_left nhất quán enforce.
    sub = await branch_service.subscription_info(db, current_user.tenant_id)
    current_user.subscription_status = sub.expiry_status
    current_user.subscription_expires_at = sub.expires_at
    current_user.subscription_days_left = sub.days_left
    # Panel "Thông tin tiệm" (owner): gói + CN dùng/max + liên hệ hỗ trợ. plan_name/branch_max
    # lấy từ `sub` (0 query thêm); branch_count = 1 count query (GUC tenant đã set); support_*
    # từ config (1 số chung mọi tenant).
    current_user.plan_name = sub.plan_name
    current_user.branch_max = sub.effective_max_branches
    current_user.branch_count = await branch_service.active_branch_count(db, current_user.tenant_id)
    current_user.support_contact = _settings.support_contact or None
    current_user.support_zalo = _settings.support_zalo or None
    return UserOut.model_validate(current_user)
