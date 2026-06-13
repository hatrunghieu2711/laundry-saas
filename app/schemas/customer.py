"""Pydantic v2 schemas cho customer. phone KHÔNG unique (khách vãng lai)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CustomerCreate(BaseModel):
    # Tạo nhanh từ POS: có thể chỉ có phone. full_name để trống -> service tự điền.
    full_name: str | None = Field(default=None, max_length=255)
    phone: str | None = Field(default=None, max_length=32)
    email: str | None = Field(default=None, max_length=255)
    notes: str | None = None


class CustomerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    full_name: str
    phone: str | None
    email: str | None
    notes: str | None
    created_at: datetime
