"""Test tenant_settings: default_turnaround_hours đọc/sửa + phân quyền.

POS đọc /settings/pos (mọi role), owner sửa /settings, staff bị 403.
"""
from httpx import AsyncClient

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


async def test_receipt_default_bilingual(client: AsyncClient, owner: dict):
    """Mẫu mặc định song ngữ 2H: logo text 2H, ghi chú bật."""
    t = await login(client, owner["phone"], owner["password"])
    r = await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    cfg = r.json()
    assert cfg["logo_text"] == "2H"
    assert cfg["logo_url"] == ""
    assert cfg["note_enabled"] is True
    assert cfg["note_vi"] and cfg["note_en"]  # có ghi chú song ngữ mặc định
    assert "blocks" not in cfg  # layout giờ cố định, không còn blocks
    assert "surcharge_enabled" not in cfg  # phụ thu giờ là tiền thật theo đơn (5.4)


async def test_receipt_update_by_owner(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    body = {
        "shop_name": "Tiệm Giặt ABC",
        "logo_text": "ABC",
        "hotline": "0258 123 456",
        "web": "giatabc.vn",
        "address": "12 Trần Phú, Nha Trang",
        "zalo_wa_kakao": "0905 000 111",
        "open_hours": "8:00 – 20:00 / Daily",
        "footer_text": "Hẹn gặp lại! / See you again!",
        "note_enabled": True,
        "note_vi": "Giữ biên nhận khi nhận đồ.",
        "note_en": "Keep this receipt to collect.",
        # client cố tình gửi logo_url bậy — server PHẢI bỏ qua (giữ "").
        "logo_url": "https://evil.example/x.png",
    }
    upd = await client.put(f"{SETTINGS}/receipt", json=body, headers=auth_headers(t))
    assert upd.status_code == 200, upd.text
    cfg = upd.json()
    assert cfg["shop_name"] == "Tiệm Giặt ABC"
    assert cfg["hotline"] == "0258 123 456"
    assert cfg["note_vi"] == "Giữ biên nhận khi nhận đồ."
    assert cfg["logo_url"] == ""  # KHÔNG nhận logo_url từ body PUT
    # đọc lại vẫn giữ
    again = await client.get(f"{SETTINGS}/receipt", headers=auth_headers(t))
    assert again.json()["zalo_wa_kakao"] == "0905 000 111"


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
