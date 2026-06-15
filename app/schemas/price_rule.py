"""Pydantic v2 schemas cho price_rules (phụ thu/giảm tự áp theo ngày) — Stage 5.4."""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

RuleType = Literal["surcharge", "discount"]
ValueType = Literal["percent", "fixed"]


class PriceRuleCreate(BaseModel):
    type: RuleType
    value_type: ValueType
    value: Decimal = Field(ge=0)
    name: str = Field(min_length=1, max_length=120)
    start_date: date
    end_date: date
    # Lưu ý: validate end>=start + percent<=100 ở SERVICE (raise APIError để client
    # nhận code ổn định INVALID_DATE_RANGE/PERCENT_TOO_HIGH).


class PriceRuleUpdate(BaseModel):
    """PUT: mọi field optional."""

    type: RuleType | None = None
    value_type: ValueType | None = None
    value: Decimal | None = Field(default=None, ge=0)
    name: str | None = Field(default=None, min_length=1, max_length=120)
    start_date: date | None = None
    end_date: date | None = None
    is_active: bool | None = None


class PriceRuleOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    type: str
    value_type: str
    value: Decimal
    name: str
    start_date: date
    end_date: date
    is_active: bool
    created_at: datetime
    updated_at: datetime


class ApplicableRules(BaseModel):
    """Rule đang hiệu lực HÔM NAY (giờ VN) để POS điền sẵn (badge 'tự áp')."""

    date: date
    surcharge: PriceRuleOut | None = None
    discount: PriceRuleOut | None = None
