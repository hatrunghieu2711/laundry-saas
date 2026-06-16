"""TenantSettings — cấu hình per-tenant (one-to-one với tenant).

Hiện chứa cấu hình Telegram (cảnh báo đóng ca) + ngưỡng lệch két.
Tách khỏi bảng `tenants` để giữ tenants gọn và chứa secret (bot token) riêng.
"""
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base
from app.models.base import Money, TimestampMixin, UpdatedAtMixin


class TenantSettings(TimestampMixin, UpdatedAtMixin, Base):
    __tablename__ = "tenant_settings"

    # tenant_id vừa là PK vừa là FK — mỗi tenant đúng một dòng settings.
    tenant_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("tenants.id"), primary_key=True
    )
    telegram_bot_token: Mapped[str | None] = mapped_column(String(255), nullable=True)
    telegram_owner_chat_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    # Ngưỡng cảnh báo lệch két (đ). Mặc định 50000.
    cash_diff_threshold: Mapped[Decimal] = mapped_column(
        Money, nullable=False, server_default=text("50000")
    )
    # Turnaround chuẩn (giờ) — POS gợi ý giờ hẹn giao = now + giá trị này. Mặc định 4.
    default_turnaround_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default=text("4")
    )
    # Tự động in phiếu sau khi tạo đơn (Stage 6.8.2). MẶC ĐỊNH TRUE = giữ hành vi 2H.
    # Tenant tắt → tạo đơn KHÔNG auto-print, nhân viên bấm "In phiếu" nếu khách cần.
    auto_print_receipt: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default=text("true")
    )
    # Cấu hình mẫu phiếu in (bill builder theo khối). NULL = dùng mẫu gốc nền tảng
    # (service tự trả DEFAULT_RECEIPT — đã có placeholder, không lộ thông tin tenant nào).
    receipt_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    # Mẫu phiếu MẶC ĐỊNH của tenant (Stage 5.10) — owner "Lưu làm mẫu mặc định";
    # "Khôi phục" sẽ về cái này. NULL = chưa lưu → fallback mẫu gốc nền tảng.
    receipt_default_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
