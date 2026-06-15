"""Schemas báo cáo (Stage 5.4). Hiện có: báo cáo giảm giá theo nhân viên."""
import uuid
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
