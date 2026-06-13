"""Pydantic v2 schemas cho order + order_items.

total_amount/subtotal LUÔN tính ở server — client gửi vào cũng bị bỏ qua khi tạo.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

OrderStatus = Literal[
    "created", "washing", "drying", "ready", "delivered", "completed", "cancelled"
]


class OrderItemIn(BaseModel):
    service_name: str = Field(min_length=1, max_length=255)
    quantity: Decimal = Field(gt=0)
    unit_price: Decimal = Field(ge=0)


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_name: str
    quantity: Decimal
    unit_price: Decimal
    subtotal: Decimal


class OrderCreate(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1)
    customer_id: uuid.UUID | None = None
    notes: str | None = None
    # owner BẮT BUỘC truyền branch_id; staff/manager lấy từ token.
    branch_id: uuid.UUID | None = None


class OrderUpdate(BaseModel):
    """PUT: sửa notes/customer. total_amount chỉ sửa được khi đơn CHƯA có payment."""

    notes: str | None = None
    customer_id: uuid.UUID | None = None
    total_amount: Decimal | None = Field(default=None, ge=0)


class OrderStatusUpdate(BaseModel):
    order_status: OrderStatus


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None
    order_code: str
    total_amount: Decimal
    payment_status: str
    order_status: str
    notes: str | None
    created_by: uuid.UUID
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]
