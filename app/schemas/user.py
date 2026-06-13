"""Pydantic v2 schemas cho user (nhân sự). password_hash KHÔNG bao giờ lộ ra."""
import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["owner", "manager", "staff", "shipper"]


class UserCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    phone: str = Field(min_length=1, max_length=32)
    password: str = Field(min_length=6, max_length=128)
    role: Role
    # branch_id: owner có thể gán bất kỳ branch; manager bị ép về branch của mình.
    branch_id: uuid.UUID | None = None
    email: str | None = Field(default=None, max_length=255)


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=255)
    phone: str | None = Field(default=None, min_length=1, max_length=32)
    password: str | None = Field(default=None, min_length=6, max_length=128)
    role: Role | None = None
    branch_id: uuid.UUID | None = None
    email: str | None = Field(default=None, max_length=255)


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    tenant_id: uuid.UUID
    branch_id: uuid.UUID | None
    role: str
    full_name: str
    phone: str
    email: str | None
    status: str
    created_at: datetime
