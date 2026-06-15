"""TenantSettings — đọc/sửa cấu hình per-tenant.

Row settings tạo LAZY: nếu tenant chưa có dòng, tạo dòng mặc định (server_default
lo các giá trị: turnaround=4, cash_diff_threshold=50000).

Mẫu phiếu (Stage 5.6): bill builder THEO KHỐI — receipt_config lưu {bilingual,
logo_url, blocks[]}. Cấu hình cũ (5.3/5.4: shop_name/note_vi… không có blocks)
được MIGRATE-ON-READ sang shape khối (giữ nội dung), lần PUT sau lưu shape mới.
"""
import copy
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


def _block(bid, btype, *, enabled=True, row=0, col="full", content=None) -> dict:
    return {"id": bid, "type": btype, "enabled": enabled, "row": row, "col": col,
            "content": content or {}}


# Bộ khối mặc định: thứ tự hợp lý, 1 khối/hàng (trừ giờ nhận+giao và số+trạng thái).
def _default_blocks() -> list[dict]:
    return [
        _block("logo", "logo", row=0, content={"shop_name": "Giặt Ủi 2H", "logo_text": "2H"}),
        _block("customer_info", "customer_info", row=1),
        _block("receiving_time", "receiving_time", row=2, col="left"),
        _block("delivery_time", "delivery_time", row=2, col="right"),
        _block("items_table", "items_table", row=3),
        _block("totals", "totals", row=4),
        _block("surcharge_discount", "surcharge_discount", enabled=False, row=5),
        _block("note", "note", row=6, content={"vi": _DEFAULT_NOTE_VI, "en": _DEFAULT_NOTE_EN}),
        _block("qr_tracking", "qr_tracking", row=7),
        _block("order_no", "order_no", row=8, col="left"),
        _block("payment_status", "payment_status", enabled=False, row=8, col="right"),
        _block("footer_contact", "footer_contact", row=9,
               content={"hotline": "", "web": "", "address": "", "zalo_wa_kakao": "",
                        "open_hours": "7:00 – 21:00 / Daily", "tagline": "Cảm ơn quý khách! / Thank you!"}),
    ]


def _default_receipt() -> dict:
    return {"bilingual": True, "logo_url": "", "blocks": _default_blocks()}


def _migrate_legacy(cfg: dict) -> dict:
    """Cấu hình cũ (5.3/5.4) → shape khối, GIỮ nội dung text owner đã nhập."""
    blocks = _default_blocks()
    by_id = {b["id"]: b for b in blocks}
    by_id["logo"]["content"] = {
        "shop_name": cfg.get("shop_name", "Giặt Ủi 2H"),
        "logo_text": cfg.get("logo_text", "2H"),
    }
    by_id["note"]["enabled"] = cfg.get("note_enabled", True)
    by_id["note"]["content"] = {"vi": cfg.get("note_vi", ""), "en": cfg.get("note_en", "")}
    by_id["footer_contact"]["content"] = {
        "hotline": cfg.get("hotline", ""), "web": cfg.get("web", ""),
        "address": cfg.get("address", ""), "zalo_wa_kakao": cfg.get("zalo_wa_kakao", ""),
        "open_hours": cfg.get("open_hours", ""), "tagline": cfg.get("footer_text", ""),
    }
    return {"bilingual": True, "logo_url": cfg.get("logo_url", ""), "blocks": blocks}


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


# ── mẫu phiếu in (bill builder theo khối) ───────────────────────────────────
async def get_receipt(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Trả cấu hình phiếu. Chưa cấu hình → mặc định. Cấu hình cũ (không có
    `blocks`) → migrate-on-read sang shape khối (giữ nội dung owner đã nhập)."""
    settings = await get_or_create(db, tenant_id)
    cfg = settings.receipt_config
    if not cfg:
        return _default_receipt()
    if "blocks" in cfg:
        return {
            "bilingual": cfg.get("bilingual", True),
            "logo_url": cfg.get("logo_url", ""),
            "blocks": cfg["blocks"],
        }
    return _migrate_legacy(cfg)  # cấu hình 5.3/5.4 cũ


async def update_receipt(
    db: AsyncSession, tenant_id: uuid.UUID, data: ReceiptConfig
) -> dict:
    """Lưu cấu trúc khối. logo_url KHÔNG nhận từ body — giữ giá trị đang lưu
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
    cfg = copy.deepcopy(settings.receipt_config) if settings.receipt_config else _default_receipt()
    cfg["logo_url"] = logo_url
    settings.receipt_config = cfg
    await db.commit()
    return await get_receipt(db, tenant_id)
