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
    """Mặc định 5.8: Tên/ĐT tách 2 khối; KHÔNG còn customer_info/note/footer/surcharge."""
    t = await login(client, owner["phone"], owner["password"])
    r = await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["bilingual"] is True and cfg["logo_url"] == ""
    types = [b["type"] for b in cfg["blocks"]]
    for t_ in ("logo", "customer_name", "customer_phone", "items_table", "totals", "qr_tracking", "order_no"):
        assert t_ in types
    for gone in ("customer_info", "note", "footer_contact", "surcharge_discount"):
        assert gone not in types
    logo = next(b for b in cfg["blocks"] if b["type"] == "logo")
    assert logo["content"]["logo_text"] == "2H"
    # Tên + ĐT ghép 1 hàng (2 cột).
    nm = next(b for b in cfg["blocks"] if b["type"] == "customer_name")
    ph = next(b for b in cfg["blocks"] if b["type"] == "customer_phone")
    assert nm["row"] == ph["row"] and {nm["col"], ph["col"]} == {"left", "right"}


async def test_receipt_update_blocks(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    body = {
        "bilingual": False,
        "blocks": [
            {"id": "logo", "type": "logo", "enabled": True, "row": 0, "col": "full",
             "content": {"shop_name": "Tiệm ABC", "logo_text": "ABC"}},
            {"id": "items_table", "type": "items_table", "enabled": True, "row": 1, "col": "full"},
            {"id": "custom_1", "type": "custom_text", "enabled": True, "row": 2, "col": "full",
             "content": {"vi": "Cảm ơn", "en": "Thanks"}},
            {"id": "qr_tracking", "type": "qr_tracking", "enabled": False, "row": 3, "col": "full"},
        ],
        "logo_url": "https://evil.example/x.png",  # phải bị bỏ
    }
    upd = await client.put(f"{SETTINGS}/receipt", json=body, headers=auth_headers(t))
    assert upd.status_code == 200, upd.text
    cfg = upd.json()
    assert cfg["bilingual"] is False
    assert cfg["logo_url"] == ""  # KHÔNG nhận logo_url từ body PUT
    logo = next(b for b in cfg["blocks"] if b["type"] == "logo")
    assert logo["content"]["shop_name"] == "Tiệm ABC"
    qr = next(b for b in cfg["blocks"] if b["type"] == "qr_tracking")
    assert qr["enabled"] is False
    # đọc lại vẫn giữ đủ 4 khối + custom_text.
    again = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    assert len(again["blocks"]) == 4
    custom = next(b for b in again["blocks"] if b["type"] == "custom_text")
    assert custom["content"]["vi"] == "Cảm ơn"


async def test_receipt_labels_format_bold_split_divider_spacer(client: AsyncClient, owner: dict):
    """Stage 5.8: nhãn tùy biến + định dạng + bold_label/bold_value RIÊNG + divider/
    spacer + ghép TỰ DO (customer_name + order_no cùng hàng)."""
    t = await login(client, owner["phone"], owner["password"])
    body = {
        "bilingual": True,
        "blocks": [
            {"id": "logo", "type": "logo", "enabled": True, "row": 0, "col": "full",
             "bold": True, "align": "center", "size": "large",
             "content": {"shop_name": "ABC", "title_vi": "PHIẾU", "title_en": "RECEIPT"}},
            {"id": "items_table", "type": "items_table", "enabled": True, "row": 1, "col": "full",
             "content": {"svc_vi": "Món", "total_en": "Sum"}},
            {"id": "div1", "type": "divider", "enabled": True, "row": 2, "col": "full",
             "content": {"style": "solid"}},
            {"id": "sp1", "type": "spacer", "enabled": True, "row": 3, "col": "full",
             "content": {"height": "medium"}},
            # ghép TỰ DO: customer_name(left) + order_no(right); bold nhãn/giá trị riêng.
            {"id": "customer_name", "type": "customer_name", "enabled": True, "row": 4, "col": "left",
             "bold_label": True, "bold_value": False, "content": {"label_vi": "Quý khách"}},
            {"id": "order_no", "type": "order_no", "enabled": True, "row": 4, "col": "right",
             "bold_label": False, "bold_value": True},
        ],
    }
    upd = await client.put(f"{SETTINGS}/receipt", json=body, headers=auth_headers(t))
    assert upd.status_code == 200, upd.text
    cfg = upd.json()
    logo = next(b for b in cfg["blocks"] if b["type"] == "logo")
    assert logo["bold"] is True and logo["align"] == "center" and logo["size"] == "large"
    assert logo["content"]["title_vi"] == "PHIẾU"
    assert next(b for b in cfg["blocks"] if b["type"] == "divider")["content"]["style"] == "solid"
    assert next(b for b in cfg["blocks"] if b["type"] == "spacer")["content"]["height"] == "medium"
    cn = next(b for b in cfg["blocks"] if b["type"] == "customer_name")
    on = next(b for b in cfg["blocks"] if b["type"] == "order_no")
    assert cn["bold_label"] is True and cn["bold_value"] is False
    assert on["bold_value"] is True
    assert cn["content"]["label_vi"] == "Quý khách"
    assert cn["row"] == on["row"] == 4 and {cn["col"], on["col"]} == {"left", "right"}
    again = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    assert next(b for b in again["blocks"] if b["type"] == "customer_name")["bold_label"] is True


async def test_receipt_56_config_gets_format_defaults(client: AsyncClient, owner: dict):
    """Cấu hình 5.6 (blocks KHÔNG có bold/align/size) → GET thêm default an toàn."""
    async with SessionFactory() as db:
        db.add(TenantSettings(
            tenant_id=owner["tenant_id"],
            receipt_config={"bilingual": True, "logo_url": "", "blocks": [
                {"id": "logo", "type": "logo", "enabled": True, "row": 0, "col": "full",
                 "content": {"logo_text": "2H"}},
                {"id": "items_table", "type": "items_table", "enabled": True, "row": 1, "col": "full"},
            ]},
        ))
        await db.commit()
    t = await login(client, owner["phone"], owner["password"])
    cfg = (await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))).json()
    logo = next(b for b in cfg["blocks"] if b["type"] == "logo")
    assert logo["bold"] is False and logo["size"] == "normal" and logo["align"] is None
    assert logo["content"]["logo_text"] == "2H"  # nội dung 5.6 cũ giữ nguyên


async def test_receipt_migrate_splits_customer_drops_note_footer(client: AsyncClient, owner: dict):
    """Cấu hình 5.6/5.7: customer_info → tách 2 khối (giữ enabled + nhãn);
    note/footer_contact/surcharge_discount BỊ BỎ; khối động giữ nguyên."""
    async with SessionFactory() as db:
        db.add(TenantSettings(
            tenant_id=owner["tenant_id"],
            receipt_config={"bilingual": True, "logo_url": "", "blocks": [
                {"id": "logo", "type": "logo", "enabled": True, "row": 0, "col": "full", "content": {"logo_text": "2H"}},
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
    assert "totals" in types and "logo" in types  # khối động giữ nguyên
    cn = next(b for b in cfg["blocks"] if b["type"] == "customer_name")
    cp = next(b for b in cfg["blocks"] if b["type"] == "customer_phone")
    assert cn["enabled"] is False and cp["enabled"] is False  # giữ trạng thái enabled
    assert cn["content"]["label_vi"] == "Họ tên" and cp["content"]["label_vi"] == "Điện thoại"
    assert cn["row"] == cp["row"] and {cn["col"], cp["col"]} == {"left", "right"}


async def test_receipt_legacy_config_migrates_drops_note_footer(client: AsyncClient, owner: dict):
    """Cấu hình 5.3/5.4 (không blocks) → bộ khối mặc định, giữ thương hiệu + logo_url;
    note/footer KHÔNG chuyển (owner gõ lại)."""
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
    logo = next(b for b in cfg["blocks"] if b["type"] == "logo")
    assert logo["content"]["shop_name"] == "Tiệm Cũ"
    assert cfg["logo_url"] == "/uploads/logo/x.png?v=9"  # giữ logo đã upload


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
