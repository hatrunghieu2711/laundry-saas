"""Báo cáo (Stage 5.4). Báo cáo giảm giá: tổng giảm + theo nhân viên, theo ngày.

Nguồn dữ liệu: discount_logs (ghi khi tạo đơn có discount > 0). Owner-only ở router.
"""
import uuid
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branch import Branch
from app.models.discount_log import DiscountLog
from app.models.order import Order
from app.models.payment import Payment
from app.models.shift import Shift
from app.models.user import User

_ZERO = Decimal(0)


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


async def owner_summary(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    *,
    from_date: date | None = None,
    to_date: date | None = None,
    branch_id: uuid.UUID | None = None,
) -> dict:
    """Báo cáo tổng cho chủ (Stage 6.3): doanh thu (theo ngày/chi nhánh), nộp chủ,
    lệch két, nợ chưa thu. Ngày theo UTC (MVP). Tiền số nguyên (đồng)."""

    def _order_window(q):
        if from_date is not None:
            q = q.where(Order.created_at >= _utc(from_date))
        if to_date is not None:
            q = q.where(Order.created_at < _utc(to_date + timedelta(days=1)))
        return q

    base_order_conds = [Order.tenant_id == tenant_id, Order.order_status != "cancelled"]
    if branch_id is not None:
        base_order_conds.append(Order.branch_id == branch_id)

    # a) DOANH THU — tổng + theo ngày (+ theo chi nhánh khi xem tất cả).
    total_revenue = await db.scalar(
        _order_window(select(func.coalesce(func.sum(Order.total_amount), _ZERO)).where(*base_order_conds))
    ) or _ZERO
    day_col = func.date(Order.created_at).label("day")
    day_rows = (
        await db.execute(
            _order_window(
                select(day_col, func.coalesce(func.sum(Order.total_amount), _ZERO).label("rev"))
                .where(*base_order_conds)
            ).group_by(day_col).order_by(day_col)
        )
    ).all()
    by_day = [{"date": r.day, "revenue": r.rev} for r in day_rows]
    by_branch: list[dict] = []
    if branch_id is None:
        br_rows = (
            await db.execute(
                _order_window(
                    select(
                        Order.branch_id, Branch.name,
                        func.coalesce(func.sum(Order.total_amount), _ZERO).label("rev"),
                    ).where(*base_order_conds)
                ).select_from(Order).outerjoin(Branch, Order.branch_id == Branch.id)
                .group_by(Order.branch_id, Branch.name).order_by(func.sum(Order.total_amount).desc())
            )
        ).all()
        by_branch = [
            {"branch_id": r.branch_id, "branch_name": r.name, "revenue": r.rev} for r in br_rows
        ]
    revenue = {"total": total_revenue, "by_day": by_day, "by_branch": by_branch}

    # b) NỘP CHỦ — dùng lại owner_handover_report.
    handover = await owner_handover_report(
        db, tenant_id, start_date=from_date, end_date=to_date, branch_id=branch_id
    )

    # c) LỆCH KÉT — ca ĐÓNG trong khoảng; liệt kê ca lệch (!=0), đếm ca khớp.
    sh_conds = [Shift.tenant_id == tenant_id, Shift.status == "closed"]
    if branch_id is not None:
        sh_conds.append(Shift.branch_id == branch_id)
    if from_date is not None:
        sh_conds.append(Shift.closed_at >= _utc(from_date))
    if to_date is not None:
        sh_conds.append(Shift.closed_at < _utc(to_date + timedelta(days=1)))
    sh_rows = (
        await db.execute(
            select(
                Shift.id, Shift.branch_id, Shift.opened_at, Shift.closed_at,
                Shift.cash_difference, User.full_name,
            )
            .select_from(Shift).outerjoin(User, Shift.closed_by == User.id)
            .where(*sh_conds).order_by(Shift.closed_at.desc())
        )
    ).all()
    diff_rows, matched, total_diff = [], 0, _ZERO
    for r in sh_rows:
        d = r.cash_difference or _ZERO
        if d == 0:
            matched += 1
        else:
            total_diff += d
            diff_rows.append({
                "shift_id": r.id, "branch_id": r.branch_id, "opened_at": r.opened_at,
                "closed_at": r.closed_at, "staff_name": r.full_name, "cash_difference": d,
            })
    cash_diff = {"total": total_diff, "count": len(diff_rows), "matched_count": matched, "rows": diff_rows}

    # d) NỢ CHƯA THU — đơn TẠO trong khoảng còn nợ (unpaid/partial/debt): tổng
    # (total_amount − đã thu) + số đơn. (Nợ tính tới hiện tại của các đơn đó.)
    paid_subq = (
        select(Payment.order_id, func.coalesce(func.sum(Payment.amount), _ZERO).label("paid"))
        .group_by(Payment.order_id).subquery()
    )
    owed_expr = Order.total_amount - func.coalesce(paid_subq.c.paid, _ZERO)
    unpaid_row = (
        await db.execute(
            _order_window(
                select(
                    func.coalesce(func.sum(owed_expr), _ZERO).label("owed"),
                    func.count().label("cnt"),
                )
                .select_from(Order)
                .outerjoin(paid_subq, Order.id == paid_subq.c.order_id)
                .where(*base_order_conds, Order.payment_status.in_(("unpaid", "partial", "debt")))
            )
        )
    ).one()
    unpaid = {"total_outstanding": unpaid_row.owed, "order_count": unpaid_row.cnt}

    return {
        "from_date": from_date, "to_date": to_date,
        "revenue": revenue, "handover": handover, "cash_diff": cash_diff, "unpaid": unpaid,
    }
