"""Pydantic v2 schemas cho tenant_settings.

- SettingsPublic: cấu hình POS cần (mọi role đọc) — KHÔNG chứa secret.
- SettingsOut: đầy đủ (owner/manager đọc) — gồm cả telegram.
- SettingsUpdate: owner sửa (mọi field optional, exclude_unset khi áp).
"""
import uuid
from decimal import Decimal
from typing import Literal

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


# ── Mẫu phiếu in: BILL BUILDER THEO KHỐI (Stage 5.6) ─────────────────────────
# Bỏ layout cứng 2H (Stage 5.3). Owner tự thêm/bớt/sắp xếp các KHỐI, ghép 2 khối/
# hàng, bật/tắt tiếng Anh toàn bill. Nhãn song ngữ vẫn cứng trong Bill.jsx; owner
# sửa NỘI DUNG khối text (logo/note/footer/custom_text). Khối dữ liệu động (bảng
# món, tổng, QR…) tự điền từ đơn — chỉ bật/tắt + sắp xếp.
BlockType = Literal[
    "logo", "customer_info", "receiving_time", "delivery_time", "items_table",
    "totals", "payment_status", "surcharge_discount", "note", "qr_tracking",
    "order_no", "footer_contact", "custom_text",
]


class ReceiptBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=40)
    type: BlockType
    enabled: bool = True
    row: int = Field(default=0, ge=0)
    # full = chiếm cả hàng; left/right = nửa hàng (2 khối hẹp/hàng).
    col: Literal["full", "left", "right"] = "full"
    # Nội dung khối text (vi/en, shop_name, hotline…). Khối động để rỗng.
    content: dict[str, str] = Field(default_factory=dict)


class ReceiptConfig(BaseModel):
    """Cấu hình mẫu phiếu in per-tenant. Đọc mọi role, sửa owner.

    `logo_url` do endpoint upload set (KHÔNG nhận trực tiếp từ client PUT để tránh
    trỏ bậy) — field_validator dưới đây loại nó khỏi body PUT nếu có gửi kèm.
    """

    model_config = ConfigDict(extra="ignore")  # bỏ qua field legacy 5.3/5.4

    bilingual: bool = True  # bật/tắt tiếng Anh toàn bill
    logo_url: str = Field(default="", max_length=255)  # set bởi POST /settings/receipt/logo
    blocks: list[ReceiptBlock] = Field(default_factory=list, max_length=40)


class ReceiptUpdate(ReceiptConfig):
    """Body cho PUT /settings/receipt — KHÔNG cho client tự đặt logo_url."""

    @field_validator("logo_url")
    @classmethod
    def _strip_logo_url(cls, v: str) -> str:
        # logo_url chỉ đổi qua endpoint upload; PUT bỏ qua giá trị client gửi.
        return ""
