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
