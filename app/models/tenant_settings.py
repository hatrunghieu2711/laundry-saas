"""TenantSettings — cấu hình per-tenant (one-to-one với tenant).

Hiện chứa cấu hình Telegram (cảnh báo đóng ca) + ngưỡng lệch két.
Tách khỏi bảng `tenants` để giữ tenants gọn và chứa secret (bot token) riêng.
"""
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Integer, String, text
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
    # Cấu hình mẫu phiếu in (Stage 4.1): text + mảng blocks {key,enabled,order}.
    # NULL = dùng mặc định (service tự trả DEFAULT_RECEIPT).
    receipt_config: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
