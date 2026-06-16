"""Pydantic v2 schemas cho shift (ca làm việc)."""
import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class ShiftOpen(BaseModel):
    opening_cash: Decimal = Field(ge=0)
    # owner BẮT BUỘC truyền branch_id; staff/manager lấy từ token (ép về branch mình).
    branch_id: uuid.UUID | None = None


class ShiftClose(BaseModel):
    closing_cash_actual: Decimal = Field(ge=0)


class ShiftSummary(BaseModel):
    """Chỉ số REALTIME của ca (Stage 6.1). cash_in_drawer dùng đúng công thức
    reconciliation lúc đóng ca. total_collected (TIỀN THU theo ca thu) vs
    shift_revenue (DOANH THU theo ca TẠO đơn) — lệch khi có đơn nợ qua ca."""

    shift_id: uuid.UUID
    status: str
    opening_cash: Decimal
    cash_in_drawer: Decimal      # két hiện tại = đầu ca + cash thu + thu quỹ − chi quỹ
    transfer_total: Decimal      # chuyển khoản + QR (không vào két)
    total_collected: Decimal     # mọi payment cash+transfer+qr trong ca (theo ca THU)
    shift_revenue: Decimal       # SUM total_amount đơn TẠO trong ca (kể cả còn nợ)
    order_count: int             # số đơn TẠO trong ca


class ShiftOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    opened_by: uuid.UUID
    opened_by_name: str | None
    closed_by: uuid.UUID | None
    closed_by_name: str | None
    opening_cash: Decimal
    closing_cash_expected: Decimal | None
    closing_cash_actual: Decimal | None
    cash_difference: Decimal | None
    total_cash: Decimal | None
    total_transfer: Decimal | None
    total_qr: Decimal | None
    total_cod: Decimal | None
    total_income: Decimal | None
    total_expense: Decimal | None
    orders_count: int | None
    status: str
    opened_at: datetime
    closed_at: datetime | None
    created_at: datetime
