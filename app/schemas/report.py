"""Schemas báo cáo. Stage 5.4: giảm giá theo nhân viên. Stage 6.2: nộp chủ."""
import uuid
from datetime import date, datetime
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


# ── Báo cáo tổng cho chủ (Stage 6.3) ────────────────────────────────────────
class RevenueDay(BaseModel):
    date: date
    revenue: Decimal


class RevenueBranch(BaseModel):
    branch_id: uuid.UUID
    branch_name: str | None
    revenue: Decimal


class RevenueGroup(BaseModel):
    total: Decimal
    by_day: list[RevenueDay]
    by_branch: list[RevenueBranch]  # chỉ điền khi xem TẤT CẢ chi nhánh


class CashDiffRow(BaseModel):
    shift_id: uuid.UUID
    branch_id: uuid.UUID
    opened_at: datetime
    closed_at: datetime | None
    staff_name: str | None
    cash_difference: Decimal
    cash_diff_reason: str | None = None  # Stage 6.33 — lý do lệch (chủ phân tích)
    reopen_count: int = 0  # Stage 6.37 — ca này từng mở lại bao nhiêu lần


class CashDiffGroup(BaseModel):
    total: Decimal       # tổng chênh lệch (net, có dấu) của các ca lệch
    count: int           # số ca LỆCH (!= 0)
    matched_count: int   # số ca KHỚP (= 0)
    rows: list[CashDiffRow]


class UnpaidGroup(BaseModel):
    total_outstanding: Decimal  # tổng còn nợ (total_amount − đã thu) đơn TẠO trong khoảng
    order_count: int


class OwnerSummary(BaseModel):
    from_date: date | None
    to_date: date | None
    revenue: RevenueGroup
    handover: OwnerHandoverReport
    cash_diff: CashDiffGroup
    unpaid: UnpaidGroup
