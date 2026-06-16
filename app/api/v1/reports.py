"""Report endpoints (Stage 5.4). Owner-only. Tenant-scoped từ token.

GET /reports/discounts: tổng giảm giá + theo nhân viên, lọc khoảng ngày + branch.
"""
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_role
from app.models.user import User
from app.schemas.report import DiscountReport, OwnerHandoverReport, OwnerSummary
from app.services import report_service

router = APIRouter(prefix="/reports", tags=["reports"])

Owner = Annotated[User, Depends(require_role("owner"))]


@router.get("/discounts", response_model=DiscountReport)
async def discount_report(
    actor: Owner,
    db: DbSession,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> DiscountReport:
    return await report_service.discount_report(
        db, actor.tenant_id,
        start_date=start_date, end_date=end_date, branch_id=branch_id,
    )


@router.get("/owner-handover", response_model=OwnerHandoverReport)
async def owner_handover_report(
    actor: Owner,
    db: DbSession,
    start_date: Annotated[date | None, Query()] = None,
    end_date: Annotated[date | None, Query()] = None,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> OwnerHandoverReport:
    """Các khoản nộp chủ theo ca đã đóng — để chủ đối chiếu tiền đã/chưa lấy."""
    return await report_service.owner_handover_report(
        db, actor.tenant_id,
        start_date=start_date, end_date=end_date, branch_id=branch_id,
    )


@router.get("/owner-summary", response_model=OwnerSummary)
async def owner_summary(
    actor: Owner,
    db: DbSession,
    from_date: Annotated[date | None, Query()] = None,
    to_date: Annotated[date | None, Query()] = None,
    branch_id: Annotated[uuid.UUID | None, Query()] = None,
) -> OwnerSummary:
    """Báo cáo tổng cho chủ (6.3): doanh thu, nộp chủ, lệch két, nợ chưa thu."""
    return await report_service.owner_summary(
        db, actor.tenant_id,
        from_date=from_date, to_date=to_date, branch_id=branch_id,
    )
