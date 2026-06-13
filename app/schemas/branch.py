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


class BranchOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    address: str | None
    phone: str | None
    code: str
    status: str
    created_at: datetime
