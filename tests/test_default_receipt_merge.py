"""Merge-on-read mẫu DEFAULT (Super Admin): tự chèn khối hệ thống BẮT BUỘC
(removable:false) còn thiếu khi ĐỌC — KHÔNG migration DB, KHÔNG đụng tenant hiện có.

Unit cho admin_default_receipt_service._merge_required_blocks: vị trí (sau neo),
idempotent (không nhân đôi), generic (mọi khối removable:false, không hardcode),
không mutate input. API + tenant-mới: xem test_admin_default_receipt.py.
"""
from app.services import admin_default_receipt_service, settings_service
from app.services.admin_default_receipt_service import _merge_required_blocks


def _stored_no_paystatus() -> dict:
    """Mẫu default đã lưu TRƯỚC Bước 1 (giống app_settings thật): có 'totals' (row 7),
    KHÔNG có payment_status. customer_name/phone ghép 1 hàng (row 3)."""
    blk = lambda i, t, row, col="full", content=None: {
        "id": i, "type": t, "enabled": True, "row": row, "col": col, "content": content or {}}
    return {
        "bilingual": True, "logo_url": "", "track_base_url": "https://t.example/",
        "branch_contact_blocks": {},
        "blocks": [
            blk("logo", "logo", 0),
            blk("brand", "custom_text", 1, content={"vi": "X"}),
            blk("title", "custom_text", 2),
            blk("cn", "customer_name", 3, "left"),
            blk("cp", "customer_phone", 3, "right"),
            blk("rt", "receiving_time", 4),
            blk("dt", "delivery_time", 5),
            blk("it", "items_table", 6),
            blk("tot", "totals", 7),
            blk("note", "custom_text", 8, content={"vi": "note"}),
            blk("qr", "qr_tracking", 9),
        ],
    }


# ── Vị trí + nội dung: payment_status ngay sau totals, trilingual, removable False ──
def test_merge_inserts_payment_status_after_totals():
    merged = _merge_required_blocks(_stored_no_paystatus())
    blocks = sorted(merged["blocks"], key=lambda b: b["row"])
    types = [b["type"] for b in blocks]

    assert types.count("payment_status") == 1
    assert types.index("payment_status") == types.index("totals") + 1  # ngay sau totals

    pb = next(b for b in blocks if b["type"] == "payment_status")
    assert pb["row"] == 8                         # totals row 7 → khối mới row 8
    assert pb["col"] == "full"                    # đứng riêng 1 hàng
    assert pb["removable"] is False
    assert pb["enabled"] is True
    assert pb["bold"] is True and pb["align"] == "center"
    assert "Đã thanh toán" in pb["content"]["paid_vi"] and "Оплачено" in pb["content"]["paid_vi"]
    assert "Chưa thanh toán" in pb["content"]["unpaid_vi"]


def test_merge_shifts_following_rows_keeps_pairing():
    merged = _merge_required_blocks(_stored_no_paystatus())
    by_id = {b["id"]: b for b in merged["blocks"]}
    # Khối SAU totals dời +1 (mở hàng trống); khối TRƯỚC giữ nguyên.
    assert by_id["note"]["row"] == 9 and by_id["qr"]["row"] == 10
    assert by_id["it"]["row"] == 6 and by_id["tot"]["row"] == 7
    # Cặp tên/ĐT (row 3, trước totals) KHÔNG bị dời, vẫn ghép 1 hàng.
    assert by_id["cn"]["row"] == 3 and by_id["cp"]["row"] == 3


# ── Idempotent: chạy lại KHÔNG nhân đôi; mẫu ĐÃ có payment_status → không chèn ──
def test_merge_idempotent():
    once = _merge_required_blocks(_stored_no_paystatus())
    twice = _merge_required_blocks(once)
    assert [b["type"] for b in once["blocks"]] == [b["type"] for b in twice["blocks"]]
    assert sum(b["type"] == "payment_status" for b in twice["blocks"]) == 1


def test_merge_noop_when_already_present():
    src = _stored_no_paystatus()
    src["blocks"].append({"id": "ps", "type": "payment_status", "enabled": True,
                          "row": 99, "col": "full", "removable": False, "content": {}})
    merged = _merge_required_blocks(src)
    ps = [b for b in merged["blocks"] if b["type"] == "payment_status"]
    assert len(ps) == 1 and ps[0]["row"] == 99  # giữ nguyên khối có sẵn, không chèn thêm


# ── KHÔNG mutate input (tránh ghi đè app_settings.value / tpl khi copy tenant) ──
def test_merge_does_not_mutate_input():
    src = _stored_no_paystatus()
    n_before = len(src["blocks"])
    rows_before = [b["row"] for b in src["blocks"]]
    _merge_required_blocks(src)
    assert len(src["blocks"]) == n_before
    assert [b["row"] for b in src["blocks"]] == rows_before
    assert not any(b["type"] == "payment_status" for b in src["blocks"])


# ── Generic: KHÔNG hardcode payment_status — mọi khối removable:false đều merge ──
def test_merge_generic_multiple_required(monkeypatch):
    def fake_defaults():
        mk = lambda i, t, **kw: {"id": i, "type": t, "enabled": True, "row": 0,
                                 "col": "full", "content": {}, **kw}
        return [
            mk("items_table", "items_table"),
            mk("totals", "totals"),
            mk("payment_status", "payment_status", removable=False,
               content={"paid_vi": "P", "unpaid_vi": "U"}),
            mk("qr_tracking", "qr_tracking"),
            mk("order_no", "order_no", removable=False),  # khối bắt buộc THỨ HAI
        ]
    monkeypatch.setattr(settings_service, "_default_blocks", fake_defaults)

    src = {"blocks": [
        {"id": "it", "type": "items_table", "enabled": True, "row": 0, "col": "full", "content": {}},
        {"id": "tot", "type": "totals", "enabled": True, "row": 1, "col": "full", "content": {}},
    ]}
    merged = _merge_required_blocks(src)
    by_type = {b["type"]: b for b in merged["blocks"]}
    assert "payment_status" in by_type and "order_no" in by_type
    assert by_type["payment_status"]["row"] == 2          # sau totals (row 1)
    assert by_type["order_no"]["row"] == 3                # sau payment_status (neo gần nhất)


def test_merge_does_not_reinsert_removed_blocks():
    # Mẫu KHÔNG có contact/footer (đã bỏ khỏi _default_blocks) → merge KHÔNG chèn lại;
    # chỉ chèn khối removable:false CÒN trong _default = payment_status.
    src = {"blocks": [
        {"id": "it", "type": "items_table", "enabled": True, "row": 0, "col": "full", "content": {}},
        {"id": "tot", "type": "totals", "enabled": True, "row": 1, "col": "full", "content": {}},
        {"id": "qr", "type": "qr_tracking", "enabled": True, "row": 2, "col": "full", "content": {}},
    ]}
    merged = _merge_required_blocks(src)
    blob = str(merged)
    assert "[Địa chỉ]" not in blob and "Cảm ơn quý khách" not in blob  # KHÔNG chèn lại
    assert sum(b["type"] == "payment_status" for b in merged["blocks"]) == 1  # chỉ payment_status


def test_merge_appends_when_no_anchor():
    # Mẫu KHÔNG có khối nào đứng trước payment_status trong _default → chèn CUỐI.
    src = {"blocks": [
        {"id": "qr", "type": "qr_tracking", "enabled": True, "row": 5, "col": "full", "content": {}},
    ]}
    merged = _merge_required_blocks(src)
    ps = next(b for b in merged["blocks"] if b["type"] == "payment_status")
    assert ps["row"] == 6  # max row (5) + 1
