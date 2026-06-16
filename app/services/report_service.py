"""Báo cáo (Stage 5.4). Báo cáo giảm giá: tổng giảm + theo nhân viên, theo ngày.

Nguồn dữ liệu: discount_logs (ghi khi tạo đơn có discount > 0). Owner-only ở router.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.discount_log import DiscountLog
from app.models.shift import Shift
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


async def owner_handover_report(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Các khoản tiền NỘP CHỦ theo ca đã đóng (handover_to_owner > 0). Lọc theo
    closed_at trong [start_date, end_date]. Để chủ đối chiếu tiền đã/chưa lấy."""
    conds = [
        Shift.tenant_id == tenant_id,
        Shift.status == "closed",
        Shift.handover_to_owner.is_not(None),
        Shift.handover_to_owner > 0,
    ]
    if branch_id is not None:
        conds.append(Shift.branch_id == branch_id)
    if start_date is not None:
        conds.append(Shift.closed_at >= _utc(start_date))
    if end_date is not None:
        conds.append(Shift.closed_at < _utc(end_date + timedelta(days=1)))

    stmt = (
        select(
            Shift.id, Shift.branch_id, Shift.opened_at, Shift.closed_at,
            Shift.handover_to_owner, User.full_name,
        )
        .select_from(Shift)
        .outerjoin(User, Shift.closed_by == User.id)
        .where(*conds)
        .order_by(Shift.closed_at.desc())
    )
    rows = (await db.execute(stmt)).all()
    report_rows = [
        {
            "shift_id": r.id, "branch_id": r.branch_id,
            "opened_at": r.opened_at, "closed_at": r.closed_at,
            "staff_name": r.full_name, "amount": r.handover_to_owner,
        }
        for r in rows
    ]
    return {
        "rows": report_rows,
        "total": sum((r["amount"] for r in report_rows), Decimal(0)),
        "count": len(report_rows),
    }
