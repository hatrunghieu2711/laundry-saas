"""Pydantic v2 schemas cho tenant_settings.

- SettingsPublic: cấu hình POS cần (mọi role đọc) — KHÔNG chứa secret.
- SettingsOut: đầy đủ (owner/manager đọc) — gồm cả telegram.
- SettingsUpdate: owner sửa (mọi field optional, exclude_unset khi áp).
"""
import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator


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


# ── Mẫu phiếu in (Stage 4.1 → nâng song ngữ 2H ở Stage 5.3) ─────────────────
# Layout phiếu giờ CỐ ĐỊNH song ngữ Việt/Anh khớp mẫu 2H (nhãn cứng ở frontend).
# Owner chỉ sửa NỘI DUNG (text + logo ảnh) và bật/tắt 2 khối: ghi chú + phụ thu.
class ReceiptConfig(BaseModel):
    """Cấu hình mẫu phiếu in per-tenant. Đọc mọi role, sửa owner.

    `logo_url` do endpoint upload set (KHÔNG nhận trực tiếp từ client PUT để tránh
    trỏ bậy) — field_validator dưới đây loại nó khỏi body PUT nếu có gửi kèm.
    """

    model_config = ConfigDict(extra="ignore")  # bỏ qua field legacy (blocks/phone cũ)

    # Thương hiệu
    shop_name: str = Field(default="", max_length=120)
    logo_text: str = Field(default="", max_length=16)  # fallback khi chưa có logo ảnh
    logo_url: str = Field(default="", max_length=255)   # set bởi POST /settings/receipt/logo

    # Chân phiếu (giá trị tự do, NHÃN song ngữ cố định ở frontend)
    hotline: str = Field(default="", max_length=60)
    web: str = Field(default="", max_length=120)
    address: str = Field(default="", max_length=200)         # Add / Địa chỉ
    zalo_wa_kakao: str = Field(default="", max_length=120)   # Zalo / WhatsApp / KakaoTalk
    open_hours: str = Field(default="", max_length=80)        # Giờ mở cửa / OPEN
    footer_text: str = Field(default="", max_length=200)      # tagline / lời cảm ơn

    # Khối ghi chú trách nhiệm (song ngữ, in nghiêng) — bật/tắt + sửa nội dung
    note_enabled: bool = True
    note_vi: str = Field(default="", max_length=600)
    note_en: str = Field(default="", max_length=600)

    # Khối phụ thu (chỉ dùng Tết) — mặc định TẮT. Tính theo % trên tổng món.
    surcharge_enabled: bool = False
    surcharge_percent: Decimal = Field(default=Decimal(0), ge=0, le=100)
    surcharge_label_vi: str = Field(default="Phụ thu Tết", max_length=60)
    surcharge_label_en: str = Field(default="Holiday surcharge", max_length=60)


class ReceiptUpdate(ReceiptConfig):
    """Body cho PUT /settings/receipt — KHÔNG cho client tự đặt logo_url."""

    @field_validator("logo_url")
    @classmethod
    def _strip_logo_url(cls, v: str) -> str:
        # logo_url chỉ đổi qua endpoint upload; PUT bỏ qua giá trị client gửi.
        return ""
