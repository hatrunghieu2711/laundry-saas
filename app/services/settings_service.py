"""TenantSettings — đọc/sửa cấu hình per-tenant.

Row settings tạo LAZY: nếu tenant chưa có dòng, tạo dòng mặc định (server_default
lo các giá trị: turnaround=4, cash_diff_threshold=50000).
"""
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.tenant_settings import TenantSettings
from app.schemas.settings import ReceiptConfig, SettingsUpdate

# Mẫu phiếu mặc định: tất cả khối bật, thứ tự chuẩn (header → … → footer).
_DEFAULT_BLOCKS = [
    "header",
    "order_code",
    "pickup_time",
    "qr_tracking",
    "items",
    "totals",
    "payment_status",
    "meta",
    "footer",
]
DEFAULT_RECEIPT = {
    "shop_name": "Giặt Ủi 2H",
    "address": "",
    "phone": "",
    "footer_text": "Cảm ơn quý khách!",
    "open_hours": "7:00 – 21:00 hằng ngày",
    "logo_text": "2H",
    "blocks": [{"key": k, "enabled": True, "order": i} for i, k in enumerate(_DEFAULT_BLOCKS)],
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
    """Trả cấu hình phiếu; chưa cấu hình → DEFAULT_RECEIPT. Merge để luôn đủ
    field text + bổ sung khối mặc định mới (nếu sau này thêm) vào cuối."""
    settings = await get_or_create(db, tenant_id)
    cfg = settings.receipt_config
    if not cfg:
        return DEFAULT_RECEIPT
    merged = {**DEFAULT_RECEIPT, **cfg}
    blocks = list(cfg.get("blocks") or DEFAULT_RECEIPT["blocks"])
    have = {b.get("key") for b in blocks}
    nxt = (max((b.get("order", 0) for b in blocks), default=-1)) + 1
    for d in DEFAULT_RECEIPT["blocks"]:
        if d["key"] not in have:
            blocks.append({"key": d["key"], "enabled": True, "order": nxt})
            nxt += 1
    merged["blocks"] = blocks
    return merged


async def update_receipt(
    db: AsyncSession, tenant_id: uuid.UUID, data: ReceiptConfig
) -> dict:
    settings = await get_or_create(db, tenant_id)
    settings.receipt_config = data.model_dump()
    await db.commit()
    return await get_receipt(db, tenant_id)
