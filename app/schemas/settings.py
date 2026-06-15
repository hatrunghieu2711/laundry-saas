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
# Stage 5.8: tách customer_info → customer_name + customer_phone; BỎ note,
# footer_contact, surcharge_discount (Văn bản tự do thay thế / gộp vào totals).
BlockType = Literal[
    "logo", "customer_name", "customer_phone", "receiving_time", "delivery_time",
    "items_table", "totals", "payment_status", "qr_tracking", "order_no",
    "custom_text", "divider", "spacer",
]


class ReceiptBlock(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: str = Field(min_length=1, max_length=40)
    type: BlockType
    enabled: bool = True
    row: int = Field(default=0, ge=0)
    # full = chiếm cả hàng; left/right = nửa hàng (ghép TỰ DO, mọi khối).
    col: Literal["full", "left", "right"] = "full"
    # Định dạng theo khối. align=None → Bill dùng mặc định theo type.
    # bold = cờ chung (khối chỉ-text: logo/custom_text…). Khối có nhãn+giá trị
    # (Tên/ĐT/giờ/số đơn) dùng bold_label + bold_value RIÊNG (Stage 5.8); None →
    # Bill fallback về `bold` (giữ định dạng cấu hình 5.7 cũ).
    bold: bool = False
    bold_label: bool | None = None
    bold_value: bool | None = None
    italic: bool = False  # Stage 5.8: in nghiêng (khối text)
    title: bool = False   # Stage 5.8: custom_text làm TIÊU ĐỀ (cỡ lớn+1, đậm, giữa)
    # Stage 5.10: khối owner THÊM hoặc do COPY → xóa được; khối GỐC hệ thống = chỉ tắt.
    removable: bool = False
    align: Literal["left", "center", "right"] | None = None
    size: Literal["small", "normal", "large"] = "normal"
    # content: nhãn (key `<name>_vi`/`<name>_en`) + giá trị text owner nhập +
    # tùy chọn khối (divider.style, spacer.height).
    content: dict[str, str] = Field(default_factory=dict)


class ReceiptConfig(BaseModel):
    """Cấu hình mẫu phiếu in per-tenant. Đọc mọi role, sửa owner.

    `logo_url` do endpoint upload set (KHÔNG nhận trực tiếp từ client PUT để tránh
    trỏ bậy) — field_validator dưới đây loại nó khỏi body PUT nếu có gửi kèm.
    """

    model_config = ConfigDict(extra="ignore")  # bỏ qua field legacy 5.3/5.4

    bilingual: bool = True  # bật/tắt tiếng Anh toàn bill
    logo_url: str = Field(default="", max_length=255)  # set bởi POST /settings/receipt/logo
    # Stage 5.8: base URL tracking per-tenant cho QR (QR = track_base_url + order_code).
    # Rỗng → Bill dùng mặc định track.giatui2h.com (để 2H không gãy).
    track_base_url: str = Field(default="", max_length=255)
    blocks: list[ReceiptBlock] = Field(default_factory=list, max_length=40)


class ReceiptUpdate(ReceiptConfig):
    """Body cho PUT /settings/receipt — KHÔNG cho client tự đặt logo_url."""

    @field_validator("logo_url")
    @classmethod
    def _strip_logo_url(cls, v: str) -> str:
        # logo_url chỉ đổi qua endpoint upload; PUT bỏ qua giá trị client gửi.
        return ""


class ReceiptDefaultStatus(BaseModel):
    """Trạng thái mẫu mặc định per-tenant (Stage 5.10)."""

    has_tenant_default: bool
