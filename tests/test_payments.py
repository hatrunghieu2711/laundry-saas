"""Test payment service — phần quan trọng nhất, test dày.

Bao phủ: paid/partial/overpay, refund, debt→resolve, NO_OPEN_SHIFT, reason/
reference bắt buộc, sai dấu, sign normalization, nhiều method → đóng ca khớp
aggregate, cách ly tenant. Viết TRƯỚC service (TDD).
"""
import uuid
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from tests.conftest import auth_headers, login

PAYMENTS = "/api/v1/payments"
REFUND = "/api/v1/payments/refund"
ORDERS = "/api/v1/orders"


def _num(x) -> int:
    return int(Decimal(str(x)))


@pytest_asyncio.fixture
async def pctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"},
                          headers=auth_headers(owner_token))
    branch_a = r.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000051", "password": "pass123",
              "role": "staff", "branch_id": branch_a["id"]},
        headers=auth_headers(owner_token),
    )
    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_token": await login(client, "0900000051", "pass123"),
        "branch_a": branch_a,
    }


_ITEMS = [{"service_name": "Giặt", "quantity": 1, "unit_price": 100000}]  # total 100000


async def _create_order(client, token, items=_ITEMS) -> dict:
    r = await client.post(ORDERS, json={"items": items}, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _open_shift(client, token) -> str:
    r = await client.post("/api/v1/shifts/open", json={"opening_cash": 0},
                          headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _pay(client, token, order_id, amount, *, method="cash", ttype="payment",
               reason=None, reference=None):
    body = {"order_id": order_id, "amount": amount, "payment_method": method,
            "transaction_type": ttype}
    if reason is not None:
        body["reason"] = reason
    if reference is not None:
        body["reference_payment_id"] = reference
    return await client.post(PAYMENTS, json=body, headers=auth_headers(token))


async def _order_status(client, token, order_id) -> str:
    r = await client.get(f"{ORDERS}/{order_id}", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()["payment_status"]


# ── thu tiền: paid / partial / overpay ──────────────────────────────────────
async def test_pay_full_marks_paid(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    resp = await _pay(client, t, order["id"], 100000)
    assert resp.status_code == 201, resp.text
    assert await _order_status(client, t, order["id"]) == "paid"


async def test_pay_partial(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    await _pay(client, t, order["id"], 40000)
    assert await _order_status(client, t, order["id"]) == "partial"


async def test_overpay_still_paid(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    await _pay(client, t, order["id"], 150000)
    assert await _order_status(client, t, order["id"]) == "paid"


# ── refund ──────────────────────────────────────────────────────────────────
async def test_full_refund_marks_refunded_and_negative(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    pay = await _pay(client, t, order["id"], 100000)
    pid = pay.json()["id"]

    ref = await _pay(client, t, order["id"], 100000, ttype="refund",
                     reason="Khách trả hàng", reference=pid)
    assert ref.status_code == 201, ref.text
    # Sign: refund LƯU ÂM.
    assert _num(ref.json()["amount"]) == -100000
    assert await _order_status(client, t, order["id"]) == "refunded"


async def test_partial_refund_back_to_partial(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    pay = await _pay(client, t, order["id"], 100000)
    await _pay(client, t, order["id"], 30000, ttype="refund",
               reason="Giảm giá bù", reference=pay.json()["id"])
    # paid_sum = 70000 -> partial (ưu tiên partial hơn refunded khi paid_sum>0).
    assert await _order_status(client, t, order["id"]) == "partial"


# ── debt → resolve_debt ─────────────────────────────────────────────────────
async def test_debt_then_resolve(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)

    d = await _pay(client, t, order["id"], 0, ttype="debt")
    assert d.status_code == 201, d.text
    assert _num(d.json()["amount"]) == 0           # debt = 0 trong dòng tiền
    assert await _order_status(client, t, order["id"]) == "debt"

    await _pay(client, t, order["id"], 100000, ttype="resolve_debt")
    assert await _order_status(client, t, order["id"]) == "paid"


# ── adjustment ──────────────────────────────────────────────────────────────
async def test_adjustment_positive_and_reason_required(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    await _pay(client, t, order["id"], 60000)  # partial

    # thiếu reason -> 422
    bad = await _pay(client, t, order["id"], 40000, ttype="adjustment")
    assert bad.status_code == 422
    assert bad.json()["code"] == "REASON_REQUIRED"

    # có reason -> cộng dương -> đủ 100000 -> paid
    ok = await _pay(client, t, order["id"], 40000, ttype="adjustment", reason="Phụ thu")
    assert ok.status_code == 201
    assert _num(ok.json()["amount"]) == 40000
    assert await _order_status(client, t, order["id"]) == "paid"


# ── lỗi: NO_OPEN_SHIFT / reason / reference / sai dấu ───────────────────────
async def test_payment_without_open_shift_409(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)  # KHÔNG mở ca
    resp = await _pay(client, t, order["id"], 100000)
    assert resp.status_code == 409
    assert resp.json()["code"] == "NO_OPEN_SHIFT"


async def test_refund_missing_reason_422(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    pay = await _pay(client, t, order["id"], 100000)
    resp = await _pay(client, t, order["id"], 50000, ttype="refund",
                      reference=pay.json()["id"])  # thiếu reason
    assert resp.status_code == 422
    assert resp.json()["code"] == "REASON_REQUIRED"


async def test_refund_missing_reference_422(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    await _pay(client, t, order["id"], 100000)
    resp = await _pay(client, t, order["id"], 50000, ttype="refund",
                      reason="Trả lại")  # thiếu reference
    assert resp.status_code == 422
    assert resp.json()["code"] == "REFERENCE_REQUIRED"


async def test_refund_reference_other_order_422(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order1 = await _create_order(client, t)
    order2 = await _create_order(client, t)
    await _open_shift(client, t)
    pay1 = await _pay(client, t, order1["id"], 100000)
    # refund order2 nhưng reference trỏ payment của order1 -> 422
    resp = await _pay(client, t, order2["id"], 50000, ttype="refund",
                      reason="Sai", reference=pay1.json()["id"])
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_REFERENCE"


async def test_negative_amount_rejected_422(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    resp = await _pay(client, t, order["id"], -100000)  # sai dấu
    assert resp.status_code == 422
    assert resp.json()["code"] == "INVALID_AMOUNT"


# ── /payments/refund shortcut ───────────────────────────────────────────────
async def test_refund_shortcut_endpoint(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    pay = await _pay(client, t, order["id"], 100000)
    resp = await client.post(
        REFUND,
        json={"order_id": order["id"], "amount": 100000, "payment_method": "cash",
              "reason": "Hủy đơn", "reference_payment_id": pay.json()["id"]},
        headers=auth_headers(t),
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["transaction_type"] == "refund"
    assert _num(resp.json()["amount"]) == -100000
    assert await _order_status(client, t, order["id"]) == "refunded"


# ── nhiều method → đóng ca khớp aggregate ───────────────────────────────────
async def test_multi_method_close_shift_aggregate(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    o1 = await _create_order(client, t)
    o2 = await _create_order(client, t)
    sid = await _open_shift(client, t)

    await _pay(client, t, o1["id"], 50000, method="cash")
    await _pay(client, t, o1["id"], 30000, method="transfer")
    await _pay(client, t, o1["id"], 20000, method="qr")
    await _pay(client, t, o2["id"], 10000, method="cash")

    close = await client.post(f"/api/v1/shifts/{sid}/close",
                              json={"closing_cash_actual": 60000},
                              headers=auth_headers(t))
    assert close.status_code == 200, close.text
    b = close.json()
    assert _num(b["total_cash"]) == 60000        # 50000 + 10000
    assert _num(b["total_transfer"]) == 30000
    assert _num(b["total_qr"]) == 20000
    assert _num(b["closing_cash_expected"]) == 60000  # opening 0 + cash 60000
    assert _num(b["cash_difference"]) == 0
    assert b["orders_count"] == 2


# ── GET list / by id ────────────────────────────────────────────────────────
async def test_list_filter_and_get_by_id(client: AsyncClient, pctx: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    p_cash = await _pay(client, t, order["id"], 40000, method="cash")
    await _pay(client, t, order["id"], 60000, method="transfer")

    lst = await client.get(f"{PAYMENTS}?order_id={order['id']}", headers=auth_headers(t))
    assert lst.status_code == 200
    assert lst.json()["total"] == 2

    by_method = await client.get(f"{PAYMENTS}?payment_method=cash", headers=auth_headers(t))
    assert by_method.json()["total"] == 1

    one = await client.get(f"{PAYMENTS}/{p_cash.json()['id']}", headers=auth_headers(t))
    assert one.status_code == 200
    assert one.json()["id"] == p_cash.json()["id"]


# ── cách ly tenant ──────────────────────────────────────────────────────────
async def test_cross_tenant_isolation(client: AsyncClient, pctx: dict, owner2: dict):
    t = pctx["staff_token"]
    order = await _create_order(client, t)
    await _open_shift(client, t)
    pay = await _pay(client, t, order["id"], 100000)

    other = await login(client, owner2["phone"], owner2["password"])
    # POST payment cho đơn tenant khác -> 404 (đơn không thuộc tenant mình)
    blocked = await _pay(client, other, order["id"], 50000)
    assert blocked.status_code == 404
    assert blocked.json()["code"] == "ORDER_NOT_FOUND"
    # GET payment tenant khác -> 404
    got = await client.get(f"{PAYMENTS}/{pay.json()['id']}", headers=auth_headers(other))
    assert got.status_code == 404
    # list -> 0
    lst = await client.get(PAYMENTS, headers=auth_headers(other))
    assert lst.json()["total"] == 0
