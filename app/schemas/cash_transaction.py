"""Pydantic v2 schemas cho sổ quỹ thu-chi (cash_transactions) — Stage 4.2.

Client gửi `amount` là MAGNITUDE (số dương); dấu (vào/ra két) do `type`. Không
ràng buộc dấu ở schema để service trả 422 INVALID_AMOUNT có code khi amount<=0.
branch_id chỉ owner truyền (staff/manager lấy từ token); shift_id/tenant_id do
service suy từ ca đang mở — KHÔNG nhận từ client.
"""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict

CashType = Literal["income", "expense"]
# Chỉ cash/transfer/qr — không cod (cod là dòng tiền giao hàng, không thuộc sổ quỹ).
CashMethod = Literal["cash", "transfer", "qr"]


class CashTransactionCreate(BaseModel):
    type: CashType
    amount: Decimal  # magnitude; service validate > 0 (422 INVALID_AMOUNT)
    category: str
    note: str | None = None
    payment_method: CashMethod = "cash"
    # owner BẮT BUỘC truyền; staff/manager bỏ qua (ép về branch mình).
    branch_id: uuid.UUID | None = None


class CashTransactionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID
    shift_id: uuid.UUID
    type: str
    amount: Decimal
    category: str
    note: str | None
    payment_method: str
    created_by: uuid.UUID
    created_by_name: str | None
    created_at: datetime
