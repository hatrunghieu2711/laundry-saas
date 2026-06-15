"""Pydantic v2 schemas cho branch. code do hệ thống sinh — client KHÔNG gửi."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class BranchCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=32)


class BranchUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    address: str | None = Field(default=None, max_length=500)
    phone: str | None = Field(default=None, max_length=32)
    # order_prefix: validate định dạng/độ dài/uniqueness ở service (422 thống nhất).
    order_prefix: str | None = Field(default=None)


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    address: str | None
    phone: str | None
    code: str
    order_prefix: str
    status: str
    created_at: datetime
