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

def _block(bid, btype, *, enabled=True, row=0, col="full", content=None) -> dict:
    return {"id": bid, "type": btype, "enabled": enabled, "row": row, "col": col,
            "content": content or {}}


# Loại khối còn hợp lệ ở Stage 5.8 (đã bỏ customer_info/note/footer_contact/
# surcharge_discount). Khối lạ/đã bỏ → loại khi đọc.
_VALID_TYPES = {
    "logo", "customer_name", "customer_phone", "receiving_time", "delivery_time",
    "items_table", "totals", "payment_status", "qr_tracking", "order_no",
    "custom_text", "divider", "spacer",
}
_DROP_TYPES = {"note", "footer_contact", "surcharge_discount"}


# Bộ khối mặc định (Stage 5.8): khối dữ liệu động + 1 custom_text làm chân phiếu.
def _default_blocks() -> list[dict]:
    return [
        _block("logo", "logo", row=0, content={"shop_name": "Giặt Ủi 2H", "logo_text": "2H"}),
        _block("customer_name", "customer_name", row=1, col="left"),
        _block("customer_phone", "customer_phone", row=1, col="right"),
        _block("receiving_time", "receiving_time", row=2, col="left"),
        _block("delivery_time", "delivery_time", row=2, col="right"),
        _block("items_table", "items_table", row=3),
        _block("totals", "totals", row=4),
        _block("qr_tracking", "qr_tracking", row=5),
        _block("order_no", "order_no", row=6),
        _block("footer_thanks", "custom_text", row=7,
               content={"vi": "Cảm ơn quý khách!", "en": "Thank you!"}),
    ]


def _default_receipt() -> dict:
    return {"bilingual": True, "logo_url": "", "blocks": _default_blocks()}


def _split_customer(b: dict) -> list[dict]:
    """customer_info (5.6/5.7) → customer_name + customer_phone, giữ enabled +
    định dạng + nhãn (name_*→label_*, tel_*→label_*)."""
    c = b.get("content") or {}
    common = {k: b[k] for k in ("enabled", "bold", "align", "size") if k in b}
    name = _block("customer_name", "customer_name", content={
        k2: c[k1] for k1, k2 in (("name_vi", "label_vi"), ("name_en", "label_en")) if k1 in c})
    phone = _block("customer_phone", "customer_phone", content={
        k2: c[k1] for k1, k2 in (("tel_vi", "label_vi"), ("tel_en", "label_en")) if k1 in c})
    name.update(common)
    phone.update(common)
    return [name, phone]


def _migrate_blocks(blocks: list[dict]) -> list[dict]:
    """Chuẩn hoá blocks về shape 5.8: tách customer_info, BỎ note/footer/surcharge,
    loại khối lạ. Giữ ghép hàng (gom theo row), chunk ≤2 khối/hàng, đánh lại row/col."""
    grouped: dict[int, list[dict]] = {}
    for b in blocks:
        grouped.setdefault(b.get("row", 0), []).append(b)
    out_rows: list[list[dict]] = []
    for r in sorted(grouped):
        cells: list[dict] = []
        for b in sorted(grouped[r], key=lambda x: 1 if x.get("col") == "right" else 0):
            t = b.get("type")
            if t in _DROP_TYPES:
                continue
            if t == "customer_info":
                cells.extend(_split_customer(b))
            elif t in _VALID_TYPES:
                cells.append(b)
            # khối lạ → bỏ
        for i in range(0, len(cells), 2):
            out_rows.append(cells[i:i + 2])
    result: list[dict] = []
    for ri, row in enumerate(out_rows):
        if len(row) == 1:
            result.append({**row[0], "row": ri, "col": "full"})
        else:
            result.append({**row[0], "row": ri, "col": "left"})
            result.append({**row[1], "row": ri, "col": "right"})
    return result


def _migrate_legacy(cfg: dict) -> dict:
    """Cấu hình cũ (5.3/5.4, không có blocks) → bộ khối mặc định, giữ thương hiệu
    (shop_name/logo_text/logo_url). note/footer KHÔNG chuyển — owner gõ lại (Stage 5.8)."""
    blocks = _default_blocks()
    blocks[0]["content"] = {
        "shop_name": cfg.get("shop_name", "Giặt Ủi 2H"),
        "logo_text": cfg.get("logo_text", "2H"),
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
        # Stage 5.8: chuẩn hoá khối (tách customer_info, bỏ note/footer/surcharge,
        # loại khối lạ) để cấu hình 5.6/5.7 cũ đọc ra shape hợp lệ.
        return {
            "bilingual": cfg.get("bilingual", True),
            "logo_url": cfg.get("logo_url", ""),
            "blocks": _migrate_blocks(cfg["blocks"]),
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
