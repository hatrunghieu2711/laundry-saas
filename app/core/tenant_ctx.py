"""ContextVar giữ tenant_id của REQUEST hiện tại — nguồn cho RLS GUC (Stage R2).

Luồng: get_current_user decode JWT → set_current_tenant(claim tenant_id) TRƯỚC khi
đọc DB. Event after_begin (app.core.database) đọc giá trị này, set vào GUC
`app.current_tenant_id` (is_local=true) cho MỌI transaction của request → RLS (R3)
lọc theo tenant. ContextVar tự cô lập theo task (asyncio) nên an toàn đa request.
"""
from contextvars import ContextVar

# default=None: request chưa-auth (login/refresh/public) → GUC rỗng (bảng ngoài RLS).
_current_tenant: ContextVar[str | None] = ContextVar("current_tenant", default=None)


def set_current_tenant(tenant_id: str | None) -> None:
    """Đặt tenant cho request hiện tại (str hóa; rỗng/None → None)."""
    _current_tenant.set(str(tenant_id) if tenant_id else None)


def get_current_tenant() -> str | None:
    return _current_tenant.get()


def reset_current_tenant() -> None:
    """Xóa context (dùng ở test + cuối luồng không-auth nếu cần)."""
    _current_tenant.set(None)
