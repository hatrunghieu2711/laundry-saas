"""TenantSettings — đọc/sửa cấu hình per-tenant.

Row settings tạo LAZY: nếu tenant chưa có dòng, tạo dòng mặc định (server_default
lo các giá trị: turnaround=4, cash_diff_threshold=50000).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_settings import TenantSettings
from app.schemas.settings import ReceiptConfig, SettingsUpdate
from app.services import logo_store

# Ghi chú trách nhiệm mặc định (song ngữ) — owner sửa được trong cấu hình.
_DEFAULT_NOTE_VI = (
    "Vui lòng giữ biên nhận và nhận đồ trong vòng 30 ngày kể từ ngày hẹn. "
    "Quá hạn, cơ sở không chịu trách nhiệm. Kiểm tra kỹ đồ trước khi rời tiệm."
)
_DEFAULT_NOTE_EN = (
    "Please keep this receipt and collect your laundry within 30 days of the due "
    "date. After that we hold no responsibility. Please check your items before leaving."
)

# Mẫu phiếu mặc định — layout song ngữ CỐ ĐỊNH (2H). receipt_config NULL → trả cái này.
DEFAULT_RECEIPT = {
    "shop_name": "Giặt Ủi 2H",
    "logo_text": "2H",
    "logo_url": "",
    "hotline": "",
    "web": "",
    "address": "",
    "zalo_wa_kakao": "",
    "open_hours": "7:00 – 21:00 / Daily",
    "footer_text": "Cảm ơn quý khách! / Thank you!",
    "note_enabled": True,
    "note_vi": _DEFAULT_NOTE_VI,
    "note_en": _DEFAULT_NOTE_EN,
}


async def get_or_create(db: AsyncSession, tenant_id: uuid.UUID) -> TenantSettings:
    settings = await db.get(TenantSettings, tenant_id)
    if settings is None:
        settings = TenantSettings(tenant_id=tenant_id)
        db.add(settings)
        await db.commit()
        settings = await db.get(TenantSettings, tenant_id)
    return settings


async def update_settings(
    db: AsyncSession, tenant_id: uuid.UUID, data: SettingsUpdate
) -> TenantSettings:
    settings = await get_or_create(db, tenant_id)
    for field, value in data.model_dump(exclude_unset=True).items():
        setattr(settings, field, value)
    await db.commit()
    return await db.get(TenantSettings, tenant_id)


# ── mẫu phiếu in ────────────────────────────────────────────────────────────
async def get_receipt(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Trả cấu hình phiếu; chưa cấu hình → DEFAULT_RECEIPT. Merge với default để
    luôn đủ field mới (cấu hình cũ thiếu field song ngữ → lấy mặc định)."""
    settings = await get_or_create(db, tenant_id)
    cfg = settings.receipt_config
    if not cfg:
        return DEFAULT_RECEIPT
    return {**DEFAULT_RECEIPT, **cfg}


async def update_receipt(
    db: AsyncSession, tenant_id: uuid.UUID, data: ReceiptConfig
) -> dict:
    """Lưu cấu hình phiếu. logo_url KHÔNG nhận từ body — giữ giá trị đang lưu
    (chỉ đổi qua POST /settings/receipt/logo)."""
    settings = await get_or_create(db, tenant_id)
    existing = settings.receipt_config or {}
    payload = data.model_dump(mode="json")
    payload["logo_url"] = existing.get("logo_url", "")
    settings.receipt_config = payload
    await db.commit()
    return await get_receipt(db, tenant_id)


async def save_logo(
    db: AsyncSession, tenant_id: uuid.UUID, raw: bytes, content_type: str | None
) -> dict:
    """Validate + tối ưu ảnh logo, lưu file tĩnh, set logo_url vào receipt_config.
    Trả cấu hình phiếu mới (đã có logo_url, kèm cache-bust)."""
    logo_url = logo_store.store_logo(tenant_id, raw, content_type)
    settings = await get_or_create(db, tenant_id)
    cfg = dict(settings.receipt_config or DEFAULT_RECEIPT)
    cfg["logo_url"] = logo_url
    settings.receipt_config = cfg
    await db.commit()
    return await get_receipt(db, tenant_id)
