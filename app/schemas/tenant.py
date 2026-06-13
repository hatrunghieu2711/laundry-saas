"""Pydantic v2 schemas cho tenant. Chỉ đọc/sửa tenant của mình (từ token)."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class TenantOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime


class TenantUpdate(BaseModel):
    """Chỉ cho sửa name ở Stage này (slug/status là việc super admin sau)."""

    name: str | None = Field(default=None, min_length=1, max_length=255)
