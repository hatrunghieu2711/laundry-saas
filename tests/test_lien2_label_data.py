"""Stage 6.9 — dữ liệu cho NHÃN liên 2 lấy từ chính order response (không cần
endpoint riêng). Xác nhận đơn trả đủ field nhãn + payment_status đúng để FE map
'Đã thanh toán / Paid' (paid) vs 'Chưa thanh toán / Unpaid' (còn lại).
"""
from httpx import AsyncClient

from tests.conftest import auth_headers
from tests.test_orders import _create_order, _open_shift, octx  # noqa: F401

LABEL_FIELDS = ("order_code", "customer_name", "created_at", "pickup_at", "payment_status", "notes")


async def test_order_has_all_label_fields(client: AsyncClient, octx: dict):
    st = octx["staff_token"]
    await _open_shift(client, st)
    # khách quen + ghi chú → nhãn hiện tên + dòng ghi chú
    cust = (await client.post("/api/v1/customers", json={"phone": "0900012321", "full_name": "Chị Lan"},
                              headers=auth_headers(st))).json()
    r = await _create_order(
        client, st,
        [{"service_name": "Giặt sấy", "quantity": 1, "unit_price": 90000}],
        customer_id=cust["id"], notes="giặt riêng đồ trắng",
        prepay=True, payment_method="cash",
    )
    assert r.status_code == 201, r.text
    o = r.json()
    for f in LABEL_FIELDS:
        assert f in o, f"thiếu field nhãn: {f}"
    assert o["order_code"]
    assert o["customer_name"] == "Chị Lan"
    assert o["notes"] == "giặt riêng đồ trắng"
    assert o["payment_status"] == "paid"  # FE → "Đã thanh toán / Paid"


async def test_pay_later_status_unpaid(client: AsyncClient, octx: dict):
    """Thu sau → unpaid → FE map 'Chưa thanh toán / Unpaid'."""
    st = octx["staff_token"]
    await _open_shift(client, st)
    r = await _create_order(client, st, [{"service_name": "Giặt", "quantity": 1, "unit_price": 50000}])
    assert r.status_code == 201, r.text
    o = r.json()
    assert o["payment_status"] == "unpaid"
    # khách vãng lai + không ghi chú → nhãn ẩn dòng ghi chú, tên = "Khách vãng lai" (FE)
    assert o["customer_name"] is None
    assert (o["notes"] or "") == ""
