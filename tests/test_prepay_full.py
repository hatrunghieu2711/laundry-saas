"""Stage 6.6.4 — Thu trước = thu ĐỦ 100% (2H KHÔNG có thu một phần).

POST /orders với prepay=True → server GHI THANH TOÁN ĐỦ = total_amount (tự tính,
KHÔNG nhận số tiền từ client). Sổ quỹ/đối soát ca + payment_logs + bill đều khớp
full total. Thu sau = chưa thu gì. Prepay không có ca mở → 409, KHÔNG tạo đơn.
"""
from decimal import Decimal

from httpx import AsyncClient

from tests.conftest import auth_headers
from tests.test_orders import _create_order, _open_shift, _num, octx  # noqa: F401

ORDERS = "/api/v1/orders"
PAYMENTS = "/api/v1/payments"


async def _payments_of(client: AsyncClient, token: str, order_id: str) -> list[dict]:
    r = await client.get(f"{PAYMENTS}?order_id={order_id}", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()["items"]


async def test_prepay_records_full_total(client: AsyncClient, octx: dict):
    """Đơn 270k + Thu trước → payment_logs đúng 270k, ca thu +270k, bill 270k."""
    st = octx["staff_token"]
    shift_id = await _open_shift(client, st)

    r = await _create_order(
        client, st,
        [{"service_name": "Giặt sấy", "quantity": 1, "unit_price": 270000}],
        prepay=True, payment_method="cash",
    )
    assert r.status_code == 201, r.text
    order = r.json()

    # Bill = total_amount = 270k; đơn đã thanh toán ĐỦ.
    assert _num(order["total_amount"]) == 270000
    assert order["payment_status"] == "paid"

    # payment_logs: ĐÚNG 1 payment = 270k (full), không phải số khác.
    pays = await _payments_of(client, st, order["id"])
    assert len(pays) == 1
    assert pays[0]["transaction_type"] == "payment"
    assert pays[0]["payment_method"] == "cash"
    assert _num(pays[0]["amount"]) == 270000

    # Đối soát ca: tiền thu +270k (vào két vì tiền mặt).
    s = (await client.get(f"/api/v1/shifts/{shift_id}/summary", headers=auth_headers(st))).json()
    assert _num(s["total_collected"]) == 270000
    assert _num(s["cash_in_drawer"]) == 270000


async def test_prepay_full_after_discount_and_method(client: AsyncClient, octx: dict):
    """Thu trước ghi full = TỔNG CỘNG sau giảm (300k − 30k = 270k), đúng phương thức."""
    st = octx["staff_token"]
    shift_id = await _open_shift(client, st)

    r = await _create_order(
        client, st,
        [{"service_name": "Giặt sấy", "quantity": 1, "unit_price": 300000}],
        prepay=True, payment_method="transfer",
        discount={"value_type": "fixed", "value": 30000},
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert _num(order["total_amount"]) == 270000
    assert order["payment_status"] == "paid"

    pays = await _payments_of(client, st, order["id"])
    assert len(pays) == 1 and _num(pays[0]["amount"]) == 270000
    assert pays[0]["payment_method"] == "transfer"

    # Transfer KHÔNG vào két tiền mặt nhưng total_collected vẫn +270k.
    s = (await client.get(f"/api/v1/shifts/{shift_id}/summary", headers=auth_headers(st))).json()
    assert _num(s["total_collected"]) == 270000


async def test_pay_later_records_nothing(client: AsyncClient, octx: dict):
    """Thu sau = chưa thu gì lúc tạo."""
    st = octx["staff_token"]
    shift_id = await _open_shift(client, st)

    r = await _create_order(
        client, st,
        [{"service_name": "Giặt sấy", "quantity": 1, "unit_price": 270000}],
    )
    assert r.status_code == 201, r.text
    order = r.json()
    assert order["payment_status"] == "unpaid"
    assert await _payments_of(client, st, order["id"]) == []

    s = (await client.get(f"/api/v1/shifts/{shift_id}/summary", headers=auth_headers(st))).json()
    assert _num(s["total_collected"]) == 0


async def test_prepay_without_open_shift_409_no_order(client: AsyncClient, octx: dict):
    """Prepay nhưng chưa mở ca → 409 NO_OPEN_SHIFT, đơn KHÔNG được tạo (không mồ côi)."""
    st = octx["staff_token"]  # chưa mở ca
    r = await _create_order(
        client, st,
        [{"service_name": "Giặt sấy", "quantity": 1, "unit_price": 270000}],
        prepay=True, payment_method="cash",
    )
    assert r.status_code == 409, r.text
    assert r.json()["code"] == "NO_OPEN_SHIFT"

    lr = await client.get(f"{ORDERS}?limit=50", headers=auth_headers(st))
    assert lr.json()["total"] == 0


async def test_client_amount_field_ignored(client: AsyncClient, octx: dict):
    """Client cố gửi 'amount'/'paid_amount' tùy ý → BỎ QUA, vẫn ghi full total."""
    st = octx["staff_token"]
    await _open_shift(client, st)

    r = await _create_order(
        client, st,
        [{"service_name": "Giặt sấy", "quantity": 1, "unit_price": 270000}],
        prepay=True, payment_method="cash",
        amount=50000, paid_amount=50000, payment_amount=50000,  # rác — phải bị bỏ
    )
    assert r.status_code == 201, r.text
    order = r.json()
    pays = await _payments_of(client, st, order["id"])
    assert len(pays) == 1 and _num(pays[0]["amount"]) == 270000  # FULL, không phải 50k
    assert order["payment_status"] == "paid"
