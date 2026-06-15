"""Báo cáo (Stage 5.4). Báo cáo giảm giá: tổng giảm + theo nhân viên, theo ngày.

Nguồn dữ liệu: discount_logs (ghi khi tạo đơn có discount > 0). Owner-only ở router.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discount_log import DiscountLog
from app.models.user import User


def _utc(d: date) -> datetime:
    return datetime.combine(d, time.min, tzinfo=timezone.utc)


async def discount_report(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Tổng giảm giá theo nhân viên trong [start_date, end_date] (bao gồm 2 đầu).

    Ngày diễn giải theo UTC (mốc created_at). MVP 1 tenant giờ VN — đủ cho báo cáo.
    """
    conds = [DiscountLog.tenant_id == tenant_id]
    if branch_id is not None:
        conds.append(DiscountLog.branch_id == branch_id)
    if start_date is not None:
        conds.append(DiscountLog.created_at >= _utc(start_date))
    if end_date is not None:
        conds.append(DiscountLog.created_at < _utc(end_date + timedelta(days=1)))

    stmt = (
        select(
            DiscountLog.user_id,
            User.full_name,
            func.count().label("order_count"),
            func.coalesce(func.sum(DiscountLog.amount), Decimal(0)).label("total"),
        )
        .select_from(DiscountLog)
        .outerjoin(User, DiscountLog.user_id == User.id)
        .where(*conds)
        .group_by(DiscountLog.user_id, User.full_name)
        .order_by(func.sum(DiscountLog.amount).desc())
    )
    rows = (await db.execute(stmt)).all()

    report_rows = [
        {
            "user_id": r.user_id,
            "user_name": r.full_name,
            "order_count": r.order_count,
            "total_discount": r.total,
        }
        for r in rows
    ]
    return {
        "rows": report_rows,
        "total_discount": sum((r["total_discount"] for r in report_rows), Decimal(0)),
        "order_count": sum(r["order_count"] for r in report_rows),
    }
