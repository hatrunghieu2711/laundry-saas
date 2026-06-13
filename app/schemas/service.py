"""Pydantic v2 schemas cho bảng giá dịch vụ (services + service_tiers)."""
import uuid
from datetime import datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

Unit = Literal["kg", "cai", "con", "bo", "luot"]
PricingType = Literal["per_unit", "tier"]


class ServiceTierIn(BaseModel):
    label: str = Field(min_length=1, max_length=64)
    # max_value = ngưỡng trên (bao gồm); None = bậc vượt ngưỡng (overflow).
    max_value: Decimal | None = Field(default=None, gt=0)
    price: Decimal = Field(ge=0)
    per_unit: bool = False
    display_order: int = 0


class ServiceTierOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    label: str
    max_value: Decimal | None
    price: Decimal
    per_unit: bool
    display_order: int


class ServiceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    unit: Unit
    pricing_type: PricingType
    unit_price: Decimal = Field(default=Decimal(0), ge=0)
    display_order: int = 0
    tiers: list[ServiceTierIn] = Field(default_factory=list)

    @model_validator(mode="after")
    def _check_tiers(self) -> "ServiceCreate":
        if self.pricing_type == "tier" and not self.tiers:
            raise ValueError("Dịch vụ tier phải có ít nhất 1 bậc giá")
        if self.pricing_type == "per_unit" and self.tiers:
            raise ValueError("Dịch vụ per_unit không có bậc giá (tiers)")
        return self


class ServiceUpdate(BaseModel):
    """PUT: mọi field optional. Truyền tiers -> thay toàn bộ bậc giá."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    unit: Unit | None = None
    pricing_type: PricingType | None = None
    unit_price: Decimal | None = Field(default=None, ge=0)
    display_order: int | None = None
    is_active: bool | None = None
    tiers: list[ServiceTierIn] | None = None


class ServiceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    unit: str
    pricing_type: str
    unit_price: Decimal
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime
    tiers: list[ServiceTierOut]
