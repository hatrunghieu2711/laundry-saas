"""Schemas báo cáo. Stage 5.4: giảm giá theo nhân viên. Stage 6.2: nộp chủ."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class DiscountReportRow(BaseModel):
    user_id: uuid.UUID | None
    user_name: str | None
    order_count: int
    total_discount: Decimal


class DiscountReport(BaseModel):
    rows: list[DiscountReportRow]
    total_discount: Decimal
    order_count: int


# ── Báo cáo nộp chủ (Stage 6.2) ─────────────────────────────────────────────
class OwnerHandoverRow(BaseModel):
    shift_id: uuid.UUID
    branch_id: uuid.UUID
    opened_at: datetime
    closed_at: datetime | None
    staff_name: str | None  # người đóng ca (nộp tiền)
    amount: Decimal


class OwnerHandoverReport(BaseModel):
    rows: list[OwnerHandoverRow]
    total: Decimal
    count: int
