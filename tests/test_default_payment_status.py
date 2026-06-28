"""Bước 1: payment_status (removable:false) vào mẫu mặc định _default_blocks.

NULL config → get_receipt = _default → CÓ payment_status sau totals. Config RIÊNG (đã lưu,
không có payment_status) KHÔNG bị chèn (chứng minh _default không tác động config đã lưu — vd 2h).
"""
from httpx import AsyncClient

from app.services.settings_service import _default_blocks, _default_receipt
from tests.conftest import auth_headers, login

RECEIPT = "/api/v1/settings/receipt"


# ── Unit: _default_blocks có payment_status sau totals, removable:false ───────
def test_default_blocks_payment_status_after_totals():
    blocks = sorted(_default_blocks(), key=lambda b: b["row"])
    types = [b["type"] for b in blocks]
    assert "payment_status" in types
    assert types.index("payment_status") == types.index("totals") + 1  # ngay sau totals

    pb = next(b for b in blocks if b["type"] == "payment_status")
    assert pb["removable"] is False         # KHÔNG xóa được
    assert pb["enabled"] is True
    assert pb["bold"] is True and pb["align"] == "center"
    assert "Đã thanh toán" in pb["content"]["paid_vi"] and "Оплачено" in pb["content"]["paid_vi"]
    assert "Chưa thanh toán" in pb["content"]["unpaid_vi"]


def test_default_receipt_branch_contact_unchanged():
    cfg = _default_receipt()
    assert any(b["type"] == "payment_status" for b in cfg["blocks"])
    assert cfg["branch_contact_blocks"] == {}  # branch_contact KHÔNG đụng (cơ chế tự render)


# ── API: tenant receipt_config NULL → _default có payment_status ─────────────
async def test_null_config_returns_payment_status(client: AsyncClient, owner: dict):
    tok = await login(client, owner["phone"], owner["password"])
    rc = (await client.get(RECEIPT, headers=auth_headers(tok))).json()
    pb = [b for b in rc["blocks"] if b["type"] == "payment_status"]
    assert len(pb) == 1
    assert pb[0]["removable"] is False
    assert pb[0]["content"]["paid_vi"].startswith("Đã thanh toán")


# ── API: config RIÊNG (đã lưu, không payment_status) KHÔNG bị chèn ────────────
async def test_saved_config_not_injected(client: AsyncClient, owner: dict):
    tok = await login(client, owner["phone"], owner["password"])
    await client.put(RECEIPT, json={
        "bilingual": True, "track_base_url": "",
        "blocks": [{"id": "it", "type": "items_table", "enabled": True, "row": 0, "col": "full"}],
        "branch_contact_blocks": {},
    }, headers=auth_headers(tok))
    rc = (await client.get(RECEIPT, headers=auth_headers(tok))).json()
    # _default đổi KHÔNG tự chèn payment_status vào config đã lưu (vd 2h giữ nguyên).
    assert not any(b["type"] == "payment_status" for b in rc["blocks"])
