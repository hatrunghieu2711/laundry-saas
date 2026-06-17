"""Pydantic v2 schemas cho order + order_items.

total_amount/subtotal LUÔN tính ở server — client gửi vào cũng bị bỏ qua khi tạo.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

OrderStatus = Literal[
    "created", "washing", "drying", "ready", "delivered", "completed", "cancelled"
]


class OrderItemIn(BaseModel):
    """Một dòng đơn. Hai cách nhập:
    - Tham chiếu bảng giá: gửi `service_id` + `quantity` (server tự tính giá/tên).
    - Nhập tay: gửi `service_name` + `unit_price` + `quantity` (không gắn service).
    """

    quantity: Decimal = Field(gt=0)
    service_id: uuid.UUID | None = None
    service_name: str | None = Field(default=None, min_length=1, max_length=255)
    unit_price: Decimal | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _check_source(self) -> "OrderItemIn":
        if self.service_id is None and (self.service_name is None or self.unit_price is None):
            raise ValueError(
                "Phải có service_id, hoặc cả service_name và unit_price (nhập tay)"
            )
        return self


class OrderItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    service_id: uuid.UUID | None
    service_name: str
    quantity: Decimal
    unit_price: Decimal
    subtotal: Decimal


class OrderAdjustmentIn(BaseModel):
    """Phụ thu/giảm nhập tay khi tạo đơn (Stage 5.4). value theo value_type:
    percent (% trên tổng món) hoặc fixed (số tiền VND). Có thì GHI ĐÈ rule tự áp."""

    value_type: Literal["percent", "fixed"]
    value: Decimal = Field(ge=0)
    reason: str | None = Field(default=None, max_length=200)


class OrderCreate(BaseModel):
    items: list[OrderItemIn] = Field(min_length=1)
    customer_id: uuid.UUID | None = None
    notes: str | None = None
    # Giờ hẹn giao BẮT BUỘC; service validate phải ở tương lai.
    pickup_at: datetime
    # owner BẮT BUỘC truyền branch_id; staff/manager lấy từ token.
    branch_id: uuid.UUID | None = None
    # Phụ thu/giảm (Stage 5.4). None → tự áp price_rules theo ngày (nếu có).
    surcharge: OrderAdjustmentIn | None = None
    discount: OrderAdjustmentIn | None = None
    # Thu trước (Stage 6.6.4): True → server GHI THANH TOÁN ĐỦ = total_amount ngay
    # khi tạo (2H KHÔNG có thu một phần). Client KHÔNG gửi số tiền — server tự tính.
    prepay: bool = False
    payment_method: Literal["cash", "transfer", "qr"] = "cash"


class OrderUpdate(BaseModel):
    """PUT: sửa notes/customer/pickup_at. total_amount chỉ sửa được khi đơn CHƯA
    có payment; pickup_at chỉ sửa khi đơn chưa completed/cancelled."""

    notes: str | None = None
    customer_id: uuid.UUID | None = None
    total_amount: Decimal | None = Field(default=None, ge=0)
    pickup_at: datetime | None = None


class OrderStatusUpdate(BaseModel):
    order_status: OrderStatus


class OrderOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    customer_id: uuid.UUID | None
    customer_name: str | None
    customer_phone: str | None
    order_code: str
    # Stage 5.4 — breakdown phụ thu/giảm (snapshot). total = subtotal + surcharge − discount.
    subtotal: Decimal
    surcharge_amount: Decimal
    discount_amount: Decimal
    surcharge_reason: str | None
    discount_reason: str | None
    total_amount: Decimal
    payment_status: str
    order_status: str
    pickup_at: datetime
    notes: str | None
    created_by: uuid.UUID
    created_by_name: str | None
    created_at: datetime
    updated_at: datetime
    items: list[OrderItemOut]
    # Chỉ set True khi giao đơn còn unpaid/partial — UI ép hỏi thanh toán.
    requires_payment: bool = False


class BoardOrder(BaseModel):
    """Một thẻ đơn trên dashboard vận hành (rút gọn, không kèm items)."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    order_code: str
    customer_name: str | None
    total_amount: Decimal
    payment_status: str
    order_status: str
    pickup_at: datetime
    is_overdue: bool
    notes: str | None  # để thẻ hiện icon ghi chú (Stage 6.12); không kèm items


class BoardSummary(BaseModel):
    total_orders: int  # tổng đơn đang hoạt động (ở tiệm)
    unpaid: int        # chưa thu: unpaid + partial
    paid: int
    debt: int
    overdue: int       # trễ hẹn


class OrderBoard(BaseModel):
    """Đơn đang hoạt động đã nhóm theo order_status để frontend dựng cột."""

    columns: dict[str, list[BoardOrder]]
    summary: BoardSummary
