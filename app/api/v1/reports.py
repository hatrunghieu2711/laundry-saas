"""Report endpoints (Stage 5.4). Owner-only. Tenant-scoped từ token.

GET /reports/discounts: tổng giảm giá + theo nhân viên, lọc khoảng ngày + branch.
"""
import uuid
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.deps import DbSession, require_role
from app.models.user import User
from app.schemas.report import DiscountReport
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
