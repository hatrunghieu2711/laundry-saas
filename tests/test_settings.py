"""Test tenant_settings: default_turnaround_hours đọc/sửa + phân quyền.

POS đọc /settings/pos (mọi role), owner sửa /settings, staff bị 403.
"""
from httpx import AsyncClient

from app.core.database import SessionFactory
from app.models.tenant_settings import TenantSettings
from tests.conftest import auth_headers, login

SETTINGS = "/api/v1/settings"


async def _staff_token(client: AsyncClient, owner_token: str) -> str:
    rb = await client.post("/api/v1/branches", json={"name": "CN A"},
                           headers=auth_headers(owner_token))
    branch = rb.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000061", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    return await login(client, "0900000061", "pass123")


async def test_pos_settings_default_turnaround(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    r = await client.get(f"{SETTINGS}/pos", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    assert r.json()["default_turnaround_hours"] == 4  # server_default


async def test_owner_update_turnaround(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    upd = await client.put(SETTINGS, json={"default_turnaround_hours": 6},
                           headers=auth_headers(t))
    assert upd.status_code == 200, upd.text
    assert upd.json()["default_turnaround_hours"] == 6
    # đọc lại từ endpoint POS.
    pos = await client.get(f"{SETTINGS}/pos", headers=auth_headers(t))
    assert pos.json()["default_turnaround_hours"] == 6
    # full settings: secret telegram mặc định None.
    full = await client.get(SETTINGS, headers=auth_headers(t))
    assert full.json()["telegram_bot_token"] is None


async def test_staff_can_read_pos_cannot_update(client: AsyncClient, owner: dict):
    owner_token = await login(client, owner["phone"], owner["password"])
    staff = await _staff_token(client, owner_token)
    # staff đọc được /pos
    ok = await client.get(f"{SETTINGS}/pos", headers=auth_headers(staff))
    assert ok.status_code == 200
    # staff không sửa được
    bad = await client.put(SETTINGS, json={"default_turnaround_hours": 8},
                           headers=auth_headers(staff))
    assert bad.status_code == 403
    # staff không đọc được full settings (chứa secret)
    full = await client.get(SETTINGS, headers=auth_headers(staff))
    assert full.status_code == 403


async def test_receipt_default_blocks(client: AsyncClient, owner: dict):
    """Mặc định 5.8: logo CHỈ ẢNH; tên tiệm là custom_text(title); Tên/ĐT tách 2 khối;
    track_base_url có mặt; KHÔNG còn customer_info/note/footer/surcharge."""
    t = await login(client, owner["phone"], owner["password"])
    r = await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["bilingual"] is True and cfg["logo_url"] == ""
    assert cfg["track_base_url"] == ""  # mặc định rỗng → Bill dùng track.giatui2h.com
    types = [b["type"] for b in cfg["blocks"]]
    for t_ in ("logo", "customer_name", "customer_phone", "items_table", "totals", "qr_tracking", "order_no"):
        assert t_ in types
    for gone in ("customer_info", "note", "footer_contact", "surcharge_discount"):
        assert gone not in types
    logo = next(b for b in cfg["blocks"] if b["type"] == "logo")
    assert logo["content"] == {}  # logo chỉ còn ảnh, không chứa text
    # tên tiệm là custom_text title — mẫu gốc dùng PLACEHOLDER (Stage 5.10).
    brand = next(b for b in cfg["blocks"] if b["type"] == "custom_text" and b.get("title"))
    assert brand["content"]["vi"] == "[Tên tiệm]"
    nm = next(b for b in cfg["blocks"] if b["type"] == "customer_name")
    ph = next(b for b in cfg["blocks"] if b["type"] == "customer_phone")
    assert nm["row"] == ph["row"] and {nm["col"], ph["col"]} == {"left", "right"}


async def test_receipt_update_blocks_format_italic_title_track(client: AsyncClient, owner: dict):
    """Lưu/đọc: italic, title (custom_text), bold_label/value, payment_status texts,
    track_base_url; logo_url bị bỏ khi PUT."""
    t = await login(client, owner["phone"], owner["password"])
    body = {
        "bilingual": True,
        "track_base_url": "https://track.abc.vn/t/",
        "blocks": [
            {"id": "logo", "type": "logo", "enabled": True, "row": 0, "col": "full"},
            {"id": "title", "type": "custom_text", "enabled": True, "row": 1, "col": "full",
             "title": True, "italic": True, "content": {"vi": "BIÊN NHẬN", "en": "RECEIPT"}},
            {"id": "items_table", "type": "items_table", "enabled": True, "row": 2, "col": "full"},
            {"id": "totals", "type": "totals", "enabled": True, "row": 3, "col": "full"},
            {"id": "order_no", "type": "order_no", "enabled": True, "row": 4, "col": "left",
             "bold_value": True},
            {"id": "payment_status", "type": "payment_status", "enabled": True, "row": 4, "col": "right",
             "content": {"paid_vi": "ĐÃ TRẢ", "paid_en": "PAID", "unpaid_vi": "CÒN NỢ", "unpaid_en": "DEBT"}},
            {"id": "qr_tracking", "type": "qr_tracking", "enabled": True, "row": 5, "col": "full"},
        ],
        "logo_url": "https://evil.example/x.png",  # phải bị bỏ
    }
    upd = await client.put(f"{SETTINGS}/receipt", json=body, headers=auth_headers(t))
    assert upd.status_code == 200, upd.text
    cfg = upd.json()
    assert cfg["logo_url"] == "" and cfg["track_base_url"] == "https://track.abc.vn/t/"
    title = next(b for b in cfg["blocks"] if b["id"] == "title")
    assert title["title"] is True and title["italic"] is True
    on = next(b for b in cfg["blocks"] if b["type"] == "order_no")
    assert on["bold_value"] is True
    ps = next(b for b in cfg["blocks"] if b["type"] == "payment_status")
    assert ps["content"]["paid_vi"] == "ĐÃ TRẢ" and ps["content"]["unpaid_vi"] == "CÒN NỢ"
    # đọc lại vẫn giữ.
    again = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    assert again["track_base_url"] == "https://track.abc.vn/t/"
    assert next(b for b in again["blocks"] if b["id"] == "title")["title"] is True


async def test_receipt_logo_title_migrates_to_custom_text(client: AsyncClient, owner: dict):
    """Stage 5.8: logo cũ chứa tên tiệm/tiêu đề → tách thành custom_text (giữ nội
    dung); logo còn lại CHỈ ẢNH (content rỗng)."""
    async with SessionFactory() as db:
        db.add(TenantSettings(
            tenant_id=owner["tenant_id"],
            receipt_config={"bilingual": True, "logo_url": "/uploads/logo/x.png?v=2", "blocks": [
                {"id": "logo", "type": "logo", "enabled": True, "row": 0, "col": "full", "bold": True,
                 "content": {"shop_name": "Giặt Sạch", "title_vi": "HÓA ĐƠN", "title_en": "INVOICE"}},
                {"id": "items_table", "type": "items_table", "enabled": True, "row": 1, "col": "full"},
            ]},
        ))
        await db.commit()
    t = await login(client, owner["phone"], owner["password"])
    cfg = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    logo = next(b for b in cfg["blocks"] if b["type"] == "logo")
    assert logo["content"] == {} and logo["bold"] is True  # chỉ ảnh, giữ định dạng
    customs = [b for b in cfg["blocks"] if b["type"] == "custom_text"]
    brand = next(b for b in customs if b["content"].get("vi") == "Giặt Sạch")
    assert brand["title"] is True
    title = next(b for b in customs if b["content"].get("vi") == "HÓA ĐƠN")
    assert title["content"]["en"] == "INVOICE"
    assert cfg["logo_url"] == "/uploads/logo/x.png?v=2"


async def test_receipt_migrate_splits_customer_drops_note_footer(client: AsyncClient, owner: dict):
    """customer_info → tách 2 khối (giữ enabled + nhãn); note/footer/surcharge BỎ."""
    async with SessionFactory() as db:
        db.add(TenantSettings(
            tenant_id=owner["tenant_id"],
            receipt_config={"bilingual": True, "logo_url": "", "blocks": [
                {"id": "customer_info", "type": "customer_info", "enabled": False, "row": 1, "col": "full",
                 "content": {"name_vi": "Họ tên", "name_en": "Name", "tel_vi": "Điện thoại", "tel_en": "Tel"}},
                {"id": "note", "type": "note", "enabled": True, "row": 2, "col": "full", "content": {"vi": "x"}},
                {"id": "footer_contact", "type": "footer_contact", "enabled": True, "row": 3, "col": "full", "content": {"hotline": "0123"}},
                {"id": "surcharge_discount", "type": "surcharge_discount", "enabled": True, "row": 4, "col": "full"},
                {"id": "totals", "type": "totals", "enabled": True, "row": 5, "col": "full"},
            ]},
        ))
        await db.commit()
    t = await login(client, owner["phone"], owner["password"])
    cfg = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    types = [b["type"] for b in cfg["blocks"]]
    assert "customer_name" in types and "customer_phone" in types and "customer_info" not in types
    for gone in ("note", "footer_contact", "surcharge_discount"):
        assert gone not in types
    assert "totals" in types
    cn = next(b for b in cfg["blocks"] if b["type"] == "customer_name")
    cp = next(b for b in cfg["blocks"] if b["type"] == "customer_phone")
    assert cn["enabled"] is False and cp["enabled"] is False
    assert cn["content"]["label_vi"] == "Họ tên" and cp["content"]["label_vi"] == "Điện thoại"
    assert cn["row"] == cp["row"] and {cn["col"], cp["col"]} == {"left", "right"}


async def test_receipt_legacy_config_migrates_drops_note_footer(client: AsyncClient, owner: dict):
    """Cấu hình 5.3/5.4 (không blocks) → bộ khối mặc định, tên tiệm → custom_text;
    giữ logo_url; note/footer KHÔNG chuyển."""
    async with SessionFactory() as db:
        db.add(TenantSettings(
            tenant_id=owner["tenant_id"],
            receipt_config={
                "shop_name": "Tiệm Cũ", "logo_text": "CU",
                "note_vi": "Ghi chú cũ", "hotline": "0123456789",
                "logo_url": "/uploads/logo/x.png?v=9",
            },
        ))
        await db.commit()
    t = await login(client, owner["phone"], owner["password"])
    cfg = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    types = [b["type"] for b in cfg["blocks"]]
    assert "note" not in types and "footer_contact" not in types
    brand = next(b for b in cfg["blocks"] if b["type"] == "custom_text" and b.get("title"))
    assert brand["content"]["vi"] == "Tiệm Cũ"
    assert cfg["logo_url"] == "/uploads/logo/x.png?v=9"


async def test_receipt_default_has_placeholders_and_structure(client: AsyncClient, owner: dict):
    """Mẫu gốc nền tảng: placeholder (KHÔNG lộ thông tin 2H) + giữ cấu trúc/định dạng."""
    t = await login(client, owner["phone"], owner["password"])
    cfg = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    blob = str(cfg)
    assert "[Tên tiệm]" in blob and "[Địa chỉ]" in blob and "[Số điện thoại]" in blob
    assert "Giặt Ủi 2H" not in blob  # KHÔNG lộ thông tin tenant 2H
    assert cfg["logo_url"] == "" and cfg["track_base_url"] == ""
    types = [b["type"] for b in cfg["blocks"]]
    for t_ in ("logo", "items_table", "totals", "qr_tracking"):
        assert t_ in types
    # cấu trúc/định dạng giữ: có tiêu đề (custom_text title) + ghi chú italic.
    assert any(b["type"] == "custom_text" and b.get("title") for b in cfg["blocks"])
    assert any(b["type"] == "custom_text" and b.get("italic") for b in cfg["blocks"])


async def test_receipt_system_blocks_not_removable_owner_added_are(client: AsyncClient, owner: dict):
    """Khối gốc hệ thống removable=false; khối owner thêm/COPY removable=true."""
    t = await login(client, owner["phone"], owner["password"])
    cfg = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    # khối hệ thống mặc định → không xóa được.
    assert all(b["removable"] is False for b in cfg["blocks"])
    # lưu cấu hình có 1 khối owner thêm (removable=true) + 1 copy của items_table.
    body = {
        "bilingual": True,
        "blocks": [
            {"id": "items_table", "type": "items_table", "enabled": True, "row": 0, "col": "full"},
            {"id": "items_table_copy", "type": "items_table", "enabled": True, "row": 1, "col": "full", "removable": True},
            {"id": "custom_1", "type": "custom_text", "enabled": True, "row": 2, "col": "full", "removable": True, "content": {"vi": "x"}},
        ],
    }
    upd = (await client.put(f"{SETTINGS}/receipt", json=body, headers=auth_headers(t))).json()
    by = {b["id"]: b for b in upd["blocks"]}
    assert by["items_table"]["removable"] is False     # gốc hệ thống
    assert by["items_table_copy"]["removable"] is True  # bản COPY xóa được
    assert by["custom_1"]["removable"] is True


async def test_receipt_old_config_custom_text_becomes_removable(client: AsyncClient, owner: dict):
    """Cấu hình cũ (chưa có `removable`): custom_text/divider/spacer → removable=true
    (giữ khả năng xóa); khối hệ thống → false."""
    async with SessionFactory() as db:
        db.add(TenantSettings(tenant_id=owner["tenant_id"], receipt_config={
            "bilingual": True, "logo_url": "", "blocks": [
                {"id": "items_table", "type": "items_table", "enabled": True, "row": 0, "col": "full"},
                {"id": "c1", "type": "custom_text", "enabled": True, "row": 1, "col": "full", "content": {"vi": "x"}},
                {"id": "d1", "type": "divider", "enabled": True, "row": 2, "col": "full"},
            ]},
        ))
        await db.commit()
    t = await login(client, owner["phone"], owner["password"])
    cfg = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    by = {b["id"]: b for b in cfg["blocks"]}
    assert by["items_table"]["removable"] is False
    assert by["c1"]["removable"] is True and by["d1"]["removable"] is True


async def test_receipt_save_and_restore_tenant_default(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    # chưa lưu → has_tenant_default false.
    st = (await client.get(f"{SETTINGS}/receipt/status", headers=auth_headers(t))).json()
    assert st["has_tenant_default"] is False
    # owner đặt cấu hình A rồi LƯU làm mẫu mặc định.
    cfgA = {"bilingual": False, "blocks": [
        {"id": "items_table", "type": "items_table", "enabled": True, "row": 0, "col": "full"},
        {"id": "c", "type": "custom_text", "enabled": True, "row": 1, "col": "full", "removable": True, "content": {"vi": "MẪU A"}},
    ]}
    await client.put(f"{SETTINGS}/receipt", json=cfgA, headers=auth_headers(t))
    sd = (await client.post(f"{SETTINGS}/receipt/save-default", headers=auth_headers(t))).json()
    assert sd["has_tenant_default"] is True
    st2 = (await client.get(f"{SETTINGS}/receipt/status", headers=auth_headers(t))).json()
    assert st2["has_tenant_default"] is True
    # đổi sang cấu hình B (khác A).
    await client.put(f"{SETTINGS}/receipt", json={"bilingual": True, "blocks": [
        {"id": "totals", "type": "totals", "enabled": True, "row": 0, "col": "full"}]},
        headers=auth_headers(t))
    # KHÔI PHỤC → về mẫu mặc định A.
    restored = (await client.post(f"{SETTINGS}/receipt/restore-default", headers=auth_headers(t))).json()
    assert restored["bilingual"] is False
    assert any(b["content"].get("vi") == "MẪU A" for b in restored["blocks"] if b["type"] == "custom_text")


async def test_receipt_restore_without_default_falls_back_to_system(client: AsyncClient, owner: dict):
    """Chưa lưu mẫu mặc định → Khôi phục dùng MẪU GỐC NỀN TẢNG (placeholder)."""
    t = await login(client, owner["phone"], owner["password"])
    await client.put(f"{SETTINGS}/receipt", json={"bilingual": True, "blocks": [
        {"id": "c", "type": "custom_text", "enabled": True, "row": 0, "col": "full", "removable": True, "content": {"vi": "RIÊNG"}}]},
        headers=auth_headers(t))
    restored = (await client.post(f"{SETTINGS}/receipt/restore-default", headers=auth_headers(t))).json()
    assert "[Tên tiệm]" in str(restored["blocks"])  # về mẫu gốc


async def test_receipt_default_tenant_isolation(client: AsyncClient, owner: dict, owner2: dict):
    t1 = await login(client, owner["phone"], owner["password"])
    await client.put(f"{SETTINGS}/receipt", json={"bilingual": True, "blocks": [
        {"id": "c", "type": "custom_text", "enabled": True, "row": 0, "col": "full", "removable": True, "content": {"vi": "T1-DEFAULT"}}]},
        headers=auth_headers(t1))
    await client.post(f"{SETTINGS}/receipt/save-default", headers=auth_headers(t1))
    # tenant 2 KHÔNG thấy mẫu mặc định của tenant 1.
    t2 = await login(client, owner2["phone"], owner2["password"])
    st2 = (await client.get(f"{SETTINGS}/receipt/status", headers=auth_headers(t2))).json()
    assert st2["has_tenant_default"] is False
    r2 = (await client.post(f"{SETTINGS}/receipt/restore-default", headers=auth_headers(t2))).json()
    assert "T1-DEFAULT" not in str(r2["blocks"])  # không lẫn mẫu tenant 1


async def test_receipt_default_owner_only(client: AsyncClient, owner: dict):
    owner_token = await login(client, owner["phone"], owner["password"])
    staff = await _staff_token(client, owner_token)
    bad = await client.post(f"{SETTINGS}/receipt/save-default", headers=auth_headers(staff))
    assert bad.status_code == 403
    bad2 = await client.post(f"{SETTINGS}/receipt/restore-default", headers=auth_headers(staff))
    assert bad2.status_code == 403


async def test_receipt_staff_read_owner_write(client: AsyncClient, owner: dict):
    owner_token = await login(client, owner["phone"], owner["password"])
    staff = await _staff_token(client, owner_token)
    ok = await client.get(f"{SETTINGS}/receipt", headers=auth_headers(staff))
    assert ok.status_code == 200  # POS đọc được
    bad = await client.put(f"{SETTINGS}/receipt", json={"shop_name": "X"},
                           headers=auth_headers(staff))
    assert bad.status_code == 403  # staff không sửa


# ── Upload logo phiếu (Stage 5.3) ───────────────────────────────────────────
def _png_bytes(size: int = 64) -> bytes:
    """Sinh 1 ảnh PNG hợp lệ trong bộ nhớ (Pillow)."""
    import io

    from PIL import Image

    buf = io.BytesIO()
    Image.new("RGB", (size, size), (10, 120, 200)).save(buf, format="PNG")
    return buf.getvalue()


async def test_logo_upload_owner(client: AsyncClient, owner: dict, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    t = await login(client, owner["phone"], owner["password"])
    files = {"file": ("logo.png", _png_bytes(), "image/png")}
    r = await client.post(f"{SETTINGS}/receipt/logo", files=files, headers=auth_headers(t))
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["logo_url"].startswith(f"/uploads/logo/{owner['tenant_id']}.png")
    # file thực sự được ghi xuống thư mục upload
    import os

    assert os.path.exists(tmp_path / "logo" / f"{owner['tenant_id']}.png")
    # GET đọc lại thấy logo_url; PUT text sau đó VẪN giữ logo_url.
    again = await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))
    assert again.json()["logo_url"] == cfg["logo_url"]
    upd = await client.put(f"{SETTINGS}/receipt", json={"shop_name": "Z"}, headers=auth_headers(t))
    assert upd.json()["logo_url"] == cfg["logo_url"]  # logo không bị PUT xoá


async def test_logo_upload_staff_forbidden(client: AsyncClient, owner: dict, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    owner_token = await login(client, owner["phone"], owner["password"])
    staff = await _staff_token(client, owner_token)
    files = {"file": ("logo.png", _png_bytes(), "image/png")}
    r = await client.post(f"{SETTINGS}/receipt/logo", files=files, headers=auth_headers(staff))
    assert r.status_code == 403


async def test_logo_upload_rejects_non_image(client: AsyncClient, owner: dict, tmp_path, monkeypatch):
    from app.core.config import get_settings

    monkeypatch.setattr(get_settings(), "upload_dir", str(tmp_path))
    t = await login(client, owner["phone"], owner["password"])
    files = {"file": ("note.txt", b"not an image", "text/plain")}
    r = await client.post(f"{SETTINGS}/receipt/logo", files=files, headers=auth_headers(t))
    assert r.status_code == 422
    assert r.json()["code"] in ("INVALID_IMAGE_TYPE", "INVALID_IMAGE")


async def test_settings_tenant_isolation(client: AsyncClient, owner: dict, owner2: dict):
    t1 = await login(client, owner["phone"], owner["password"])
    await client.put(SETTINGS, json={"default_turnaround_hours": 9}, headers=auth_headers(t1))
    t2 = await login(client, owner2["phone"], owner2["password"])
    pos2 = await client.get(f"{SETTINGS}/pos", headers=auth_headers(t2))
    assert pos2.json()["default_turnaround_hours"] == 4  # tenant 2 không bị ảnh hưởng
