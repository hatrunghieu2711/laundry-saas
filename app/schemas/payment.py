"""Pydantic v2 schemas cho payment.

Client gửi `amount` là MAGNITUDE (số dương); service áp dấu theo transaction_type
và LƯU vào DB (refund/cancel_paid lưu âm). branch_id/tenant_id/shift_id KHÔNG
nhận từ client — service lấy từ order + ca đang mở.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

PaymentMethod = Literal["cash", "transfer", "qr", "cod"]
TransactionType = Literal[
    "payment", "refund", "adjustment", "debt", "resolve_debt", "cancel_paid"
]


class PaymentCreate(BaseModel):
    order_id: uuid.UUID
    # magnitude; service áp dấu theo type. Không ràng buộc dấu ở schema để
    # service trả 422 INVALID_AMOUNT có code khi client gửi sai dấu (<=0).
    amount: Decimal
    payment_method: PaymentMethod
    transaction_type: TransactionType
    reason: str | None = None
    reference_payment_id: uuid.UUID | None = None


class RefundCreate(BaseModel):
    """Shortcut tạo refund. transaction_type cố định = 'refund'."""

    order_id: uuid.UUID
    amount: Decimal = Field(gt=0)
    payment_method: PaymentMethod
    reason: str = Field(min_length=1)
    reference_payment_id: uuid.UUID


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    order_id: uuid.UUID | None
    shift_id: uuid.UUID
    amount: Decimal
    payment_method: str
    transaction_type: str
    reason: str | None
    reference_payment_id: uuid.UUID | None
    created_by: uuid.UUID
    created_by_name: str | None
    created_at: datetime
