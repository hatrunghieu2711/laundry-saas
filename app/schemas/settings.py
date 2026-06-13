"""Pydantic v2 schemas cho tenant_settings.

- SettingsPublic: cấu hình POS cần (mọi role đọc) — KHÔNG chứa secret.
- SettingsOut: đầy đủ (owner/manager đọc) — gồm cả telegram.
- SettingsUpdate: owner sửa (mọi field optional, exclude_unset khi áp).
"""
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field


class SettingsPublic(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    default_turnaround_hours: int


class SettingsOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    tenant_id: uuid.UUID
    default_turnaround_hours: int
    cash_diff_threshold: Decimal
    telegram_bot_token: str | None
    telegram_owner_chat_id: str | None


class SettingsUpdate(BaseModel):
    default_turnaround_hours: int | None = Field(default=None, ge=0, le=72)
    cash_diff_threshold: Decimal | None = Field(default=None, ge=0)
    telegram_bot_token: str | None = None
    telegram_owner_chat_id: str | None = None


# ── Mẫu phiếu in (Stage 4.1) ────────────────────────────────────────────────
class ReceiptBlock(BaseModel):
    key: str = Field(min_length=1, max_length=32)
    enabled: bool = True
    order: int = 0


class ReceiptConfig(BaseModel):
    """Cấu hình mẫu phiếu in per-tenant. Đọc mọi role, sửa owner."""

    shop_name: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=200)
    phone: str = Field(default="", max_length=40)
    footer_text: str = Field(default="", max_length=200)
    open_hours: str = Field(default="", max_length=80)
    logo_text: str = Field(default="", max_length=16)
    blocks: list[ReceiptBlock] = Field(default_factory=list)
