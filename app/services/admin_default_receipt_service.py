"""Mẫu in MẶC ĐỊNH system-wide (Super Admin).

Lưu app_settings key='default_receipt' (NGOÀI RLS → admin GUC rỗng đọc/ghi được).
⚠️ KHÁC receipt_default_config (mẫu mặc định PER-TENANT, Stage 5.10) — đừng nhầm.

Mẫu chuẩn = phần CHUNG: blocks + bilingual + track_base_url. KHÔNG branch_contact_blocks
(per-branch, key=branch_id) / logo_url (per-tenant) / auto_print (cột riêng). Tạo tenant
mới COPY mẫu này vào receipt_config; tenant tự sửa sau (không liên kết ngược).
"""
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import AppSettings
from app.schemas.settings import ReceiptUpdate
from app.services import settings_service

_KEY = "default_receipt"


async def get_stored_default_receipt(db: AsyncSession) -> dict[str, Any] | None:
    """Mẫu chuẩn ĐÃ lưu (None nếu admin CHƯA set). Dùng cho create_tenant copy."""
    row = await db.get(AppSettings, _KEY)
    return row.value if row is not None else None


async def get_default_receipt(db: AsyncSession) -> dict[str, Any]:
    """GET endpoint: chưa set → _default_receipt() (placeholder — điểm khởi đầu cho admin)."""
    stored = await get_stored_default_receipt(db)
    return stored if stored is not None else settings_service._default_receipt()


async def set_default_receipt(db: AsyncSession, data: ReceiptUpdate) -> dict[str, Any]:
    """Validate (ReceiptUpdate đã ép logo_url='') + STRIP branch_contact_blocks={} →
    chỉ giữ phần CHUNG. Upsert app_settings key='default_receipt' (ngoài RLS)."""
    payload = data.model_dump(mode="json")
    payload["branch_contact_blocks"] = {}  # mẫu chuẩn KHÔNG chứa liên hệ per-CN
    payload["logo_url"] = ""                # logo per-tenant (ReceiptUpdate đã ép "")
    stmt = (
        pg_insert(AppSettings)
        .values(key=_KEY, value=payload)
        .on_conflict_do_update(
            index_elements=["key"],
            set_={"value": payload, "updated_at": func.now()},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return payload
