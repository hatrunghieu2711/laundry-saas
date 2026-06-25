"""app_settings — cấu hình HỆ THỐNG key-value (NGOÀI RLS).

Không thuộc tenant nào → giống tenants/plans/admins: KHÔNG ENABLE ROW LEVEL SECURITY,
admin (GUC rỗng, laundry_app non-bypass) đọc/ghi trực tiếp. Hiện dùng cho mẫu in chuẩn
(key='default_receipt'); mở rộng cho global config khác về sau.
"""
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from app.core.database import Base


class AppSettings(Base):
    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=text("now()"), nullable=False
    )
