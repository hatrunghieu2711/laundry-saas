"""Logic trang tracking công khai. Chỉ ĐỌC, chỉ trả field an toàn (xem schema)."""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.models.branch import Branch
from app.models.log import OrderTrackingLog
from app.models.order import Order


async def get_public_tracking(db: AsyncSession, order_code: str) -> dict:
    """Tra cứu công khai theo order_code.

    LƯU Ý: order_code chỉ unique trong 1 tenant (uq (tenant_id, order_code)), không
    unique toàn cục — MVP 1 tenant nên đủ định danh. Nếu (hiếm) trùng giữa các
    tenant, trả bản MỚI NHẤT cho ổn định. Xem nợ kỹ thuật khi onboard tenant #2.
    """
    order = await db.scalar(
        select(Order)
        .where(Order.order_code == order_code)
        .order_by(Order.created_at.desc())
        .limit(1)
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
