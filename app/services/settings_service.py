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


# Ghi chú trách nhiệm MẪU (song ngữ) — khối custom_text trong mẫu gốc.
_SAMPLE_NOTE_VI = (
    "Vui lòng giữ biên nhận và nhận đồ trong vòng 30 ngày kể từ ngày hẹn. "
    "Quá hạn, cơ sở không chịu trách nhiệm."
)
_SAMPLE_NOTE_EN = (
    "Please keep this receipt and collect within 30 days of the due date. "
    "After that we hold no responsibility."
)

# MẪU GỐC NỀN TẢNG (Stage 5.10) — cấu trúc/định dạng/nhãn chuẩn (giống bill 2H đẹp)
# nhưng tên tiệm/địa chỉ/SĐT là PLACEHOLDER (không lộ thông tin tenant nào), logo
# trống, track_base_url trống. Tenant mới khởi tạo từ mẫu này (qua fallback get_receipt).
# Khối hệ thống KHÔNG đặt `removable` → chỉ tắt, không xóa (chốt Stage 5.10).
def _default_blocks() -> list[dict]:
    return [
        _block("logo", "logo", row=0),  # chỉ ảnh (logo_url top-level)
        {**_block("brand", "custom_text", row=1, content={"vi": "[Tên tiệm]"}), "title": True},
        {**_block("title", "custom_text", row=2, content={"vi": "BIÊN NHẬN", "en": "RECEIPT"}),
         "bold": True, "align": "center"},
        _block("customer_name", "customer_name", row=3, col="left"),
        _block("customer_phone", "customer_phone", row=3, col="right"),
        _block("receiving_time", "receiving_time", row=4, col="left"),
        _block("delivery_time", "delivery_time", row=4, col="right"),
        _block("items_table", "items_table", row=5),
        _block("totals", "totals", row=6),
        {**_block("note", "custom_text", row=7,
                  content={"vi": _SAMPLE_NOTE_VI, "en": _SAMPLE_NOTE_EN}),
         "italic": True, "size": "small"},
        _block("qr_tracking", "qr_tracking", row=8),
        _block("order_no", "order_no", row=9),
        {**_block("contact", "custom_text", row=10,
                  content={"vi": "[Địa chỉ] · [Số điện thoại]"}), "size": "small"},
        _block("footer_thanks", "custom_text", row=11,
               content={"vi": "Cảm ơn quý khách!", "en": "Thank you!"}),
    ]


def _default_receipt() -> dict:
    return {"bilingual": True, "logo_url": "", "track_base_url": "", "blocks": _default_blocks(),
            "branch_contact_blocks": {}}


def _migrate_branch_contact_blocks(raw) -> dict:
    """Khu "Liên hệ theo chi nhánh": mỗi CN một MẢNG khối → chạy _migrate_blocks
    (validate/loại khối lạ, chunk ≤2/hàng, gán removable) như khối thường. raw
    None/không phải dict → {}; mảng không phải list → bỏ CN đó."""
    if not isinstance(raw, dict):
        return {}
    return {bid: _migrate_blocks(blks) for bid, blks in raw.items() if isinstance(blks, list)}


def _split_customer(b: dict) -> list[dict]:
    """customer_info (5.6/5.7) → customer_name + customer_phone, giữ enabled +
    định dạng + nhãn (name_*→label_*, tel_*→label_*)."""
    c = b.get("content") or {}
    common = {k: b[k] for k in ("enabled", "bold", "italic", "align", "size") if k in b}
    name = _block("customer_name", "customer_name", content={
        k2: c[k1] for k1, k2 in (("name_vi", "label_vi"), ("name_en", "label_en")) if k1 in c})
    phone = _block("customer_phone", "customer_phone", content={
        k2: c[k1] for k1, k2 in (("tel_vi", "label_vi"), ("tel_en", "label_en")) if k1 in c})
    name.update(common)
    phone.update(common)
    return [name, phone]


def _logo_titles(b: dict) -> list[dict]:
    """Stage 5.8: logo cũ có tên tiệm / tiêu đề → TÁCH thành custom_text (giữ nội
    dung). Trả các khối custom_text (mỗi khối 1 hàng riêng, đứng sau logo ảnh)."""
    c = b.get("content") or {}
    out: list[dict] = []
    brand = c.get("shop_name") or c.get("logo_text")
    if brand:
        out.append({**_block("logo_brand", "custom_text", content={"vi": brand}),
                    "title": True, "removable": True})
    if c.get("title_vi") or c.get("title_en"):
        out.append({**_block("logo_title", "custom_text",
                             content={"vi": c.get("title_vi", "BIÊN NHẬN"),
                                      "en": c.get("title_en", "RECEIPT")}),
                    "bold": True, "align": "center", "removable": True})
    return out


def _migrate_blocks(blocks: list[dict]) -> list[dict]:
    """Chuẩn hoá blocks về shape 5.8: tách customer_info; logo → CHỈ ẢNH (tên tiệm/
    tiêu đề → custom_text); BỎ note/footer/surcharge + khối lạ. Giữ ghép hàng,
    chunk ≤2 khối/hàng, đánh lại row/col."""
    grouped: dict[int, list[dict]] = {}
    for b in blocks:
        grouped.setdefault(b.get("row", 0), []).append(b)
    out_rows: list[list[dict]] = []
    for r in sorted(grouped):
        cells: list[dict] = []
        extra_rows: list[list[dict]] = []  # khối spawn full-width (tiêu đề từ logo)
        for b in sorted(grouped[r], key=lambda x: 1 if x.get("col") == "right" else 0):
            t = b.get("type")
            if t in _DROP_TYPES:
                continue
            if t == "customer_info":
                cells.extend(_split_customer(b))
            elif t == "logo":
                cells.append({**b, "content": {}})  # logo chỉ còn ảnh
                extra_rows.extend([tb] for tb in _logo_titles(b))
            elif t in _VALID_TYPES:
                cells.append(b)
            # khối lạ → bỏ
        for i in range(0, len(cells), 2):
            out_rows.append(cells[i:i + 2])
        out_rows.extend(extra_rows)  # tiêu đề tách từ logo đứng ngay sau
    result: list[dict] = []
    for ri, row in enumerate(out_rows):
        if len(row) == 1:
            result.append({**row[0], "row": ri, "col": "full"})
        else:
            result.append({**row[0], "row": ri, "col": "left"})
            result.append({**row[1], "row": ri, "col": "right"})
    # Stage 5.10: cấu hình CŨ (5.6–5.9) chưa có `removable` → suy theo loại
    # (custom_text/divider/spacer của owner = xóa được; khối hệ thống = chỉ tắt).
    # Cấu hình mới đã có `removable` → giữ nguyên.
    for b in result:
        if "removable" not in b:
            b["removable"] = b.get("type") in ("custom_text", "divider", "spacer")
    return result


def _migrate_legacy(cfg: dict) -> dict:
    """Cấu hình cũ (5.3/5.4, không có blocks) → bộ khối mặc định, giữ thương hiệu
    (tên tiệm → custom_text title) + logo_url. note/footer KHÔNG chuyển (Stage 5.8)."""
    blocks = _default_blocks()
    brand = cfg.get("shop_name") or cfg.get("logo_text") or "Giặt Ủi 2H"
    # blocks[1] là custom_text 'brand' (title).
    blocks[1]["content"] = {"vi": brand}
    return {"bilingual": True, "logo_url": cfg.get("logo_url", ""),
            "track_base_url": "", "blocks": blocks, "branch_contact_blocks": {}}


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
        # Stage 5.8: chuẩn hoá khối (tách customer_info, logo→ảnh, bỏ note/footer/
        # surcharge, loại khối lạ) để cấu hình 5.6/5.7 cũ đọc ra shape hợp lệ.
        return {
            "bilingual": cfg.get("bilingual", True),
            "logo_url": cfg.get("logo_url", ""),
            "track_base_url": cfg.get("track_base_url", ""),
            "blocks": _migrate_blocks(cfg["blocks"]),
            # ⚠️ Cổng 2: phải thêm key này (dict trả dựng tay), nếu không GET drop dù
            # đã lưu được. Mỗi mảng CN chạy _migrate_blocks như khối thường.
            "branch_contact_blocks": _migrate_branch_contact_blocks(cfg.get("branch_contact_blocks")),
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


# ── mẫu mặc định per-tenant (Stage 5.10) ─────────────────────────────────────
async def has_receipt_default(db: AsyncSession, tenant_id: uuid.UUID) -> bool:
    settings = await get_or_create(db, tenant_id)
    return settings.receipt_default_config is not None


async def save_receipt_default(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Lưu cấu hình ĐANG DÙNG thành mẫu mặc định của tenant (để Khôi phục)."""
    active = await get_receipt(db, tenant_id)  # resolved (đầy đủ, hợp lệ)
    settings = await get_or_create(db, tenant_id)
    settings.receipt_default_config = active
    await db.commit()
    return active


async def restore_receipt_default(db: AsyncSession, tenant_id: uuid.UUID) -> dict:
    """Khôi phục: cấu hình đang dùng = mẫu mặc định tenant (đã lưu) hoặc — nếu
    CHƯA lưu — fallback MẪU GỐC NỀN TẢNG. KHÔNG hoàn tác."""
    settings = await get_or_create(db, tenant_id)
    settings.receipt_config = copy.deepcopy(settings.receipt_default_config) or _default_receipt()
    await db.commit()
    return await get_receipt(db, tenant_id)
