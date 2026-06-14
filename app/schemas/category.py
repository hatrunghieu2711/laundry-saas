"""Pydantic v2 schemas cho danh mục dịch vụ (categories) — Stage 4.3."""
import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class CategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=64)
    icon: str | None = Field(default=None, max_length=32)
    display_order: int = 0


class CategoryUpdate(BaseModel):
    """PUT: mọi field optional."""

    name: str | None = Field(default=None, min_length=1, max_length=64)
    icon: str | None = Field(default=None, max_length=32)
    display_order: int | None = None
    is_active: bool | None = None


class CategoryReorder(BaseModel):
    """Sắp thứ tự: danh sách id theo thứ tự mong muốn (display_order = index)."""

    ids: list[uuid.UUID] = Field(min_length=1)


class CategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    name: str
    icon: str | None
    display_order: int
    is_active: bool
    created_at: datetime
    updated_at: datetime


class CategoryBrief(BaseModel):
    """Info gọn nhúng vào ServiceOut để frontend render tab/nhãn."""

    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    icon: str | None
    display_order: int
