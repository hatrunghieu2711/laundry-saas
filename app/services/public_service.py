"""Logic trang tracking công khai. Chỉ ĐỌC, chỉ trả field an toàn (xem schema)."""
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.branch import Branch
from app.models.log import OrderTrackingLog
from app.models.order import Order
from app.services import tenant_service

_SET_GUC = "SELECT set_config('app.current_tenant_id', :tid, true)"


async def get_public_tracking(db: AsyncSession, slug: str, order_code: str) -> dict:
    """Tra cứu công khai theo (slug, order_code) — MULTI-TENANT.

    order_code chỉ unique trong 1 tenant (uq (tenant_id, order_code)) → BẮT BUỘC biết
    tenant. slug (mã cửa hàng) → tenant. ⚠️ Endpoint CÔNG KHAI (không auth) → GUC rỗng;
    orders STRICT RLS. Phải set_config(GUC=tenant.id) TRƯỚC khi query (pattern create_tenant,
    KHÔNG bypass RLS) — nếu không, RLS chặn → 404 (bug cũ thời 1 tenant). slug sai/tenant
    khóa → cùng 404 ORDER_NOT_FOUND (không lộ tenant tồn tại/khóa).
    """
    tenant = await tenant_service.get_tenant_by_slug(db, slug)
    if tenant is None or tenant.status != "active":
        raise APIError(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn")

    await db.execute(text(_SET_GUC), {"tid": str(tenant.id)})
    order = await db.scalar(
        select(Order).where(
            Order.order_code == order_code, Order.tenant_id == tenant.id
        )
    )
    if order is None:
        raise APIError(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn")

    branch = await db.get(Branch, order.branch_id)
    logs = (
        await db.execute(
            select(OrderTrackingLog)
            .where(OrderTrackingLog.order_id == order.id)
            .order_by(OrderTrackingLog.created_at.asc())
        )
    ).scalars().all()

    return {
        "order_code": order.order_code,
        "order_status": order.order_status,
        "pickup_at": order.pickup_at,
        "branch": {
            "name": branch.name,
            "address": branch.address,
            "phone": branch.phone,
        },
        "timeline": [{"status": log.status, "at": log.created_at} for log in logs],
    }
