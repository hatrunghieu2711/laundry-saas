"""Test phụ thu & giảm giá vào TIỀN THẬT (Stage 5.4). Viết TRƯỚC (TDD).

total_amount = subtotal + surcharge_amount - discount_amount. Snapshot lúc tạo đơn
(bất biến như giá món). Reconciliation đóng ca khớp vì payment thu theo total thật.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import auth_headers, login

ORDERS = "/api/v1/orders"
RULES = "/api/v1/price-rules"


def _num(x) -> int:
    return int(Decimal(str(x)))


def _vn_today():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date()


def _pickup(h: float = 4) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=h)).isoformat()


# subtotal = 2×50000 + 1×100000 = 200000
ITEMS = [
    {"service_name": "Giặt thường", "quantity": 2, "unit_price": 50000},
    {"service_name": "Giặt khô", "quantity": 1, "unit_price": 100000},
]


@pytest_asyncio.fixture
async def actx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"},
                          headers=auth_headers(owner_token))
    branch = r.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000052", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    staff_token = await login(client, "0900000052", "pass123")
    # mở ca (cho phần thanh toán/đóng ca).
    await client.post("/api/v1/shifts/open", json={"opening_cash": 100000},
                      headers=auth_headers(staff_token))
    return {"owner": owner, "owner_token": owner_token, "staff_token": staff_token, "branch": branch}


async def _create(client: AsyncClient, token: str, **extra):
    body = {"items": ITEMS, "pickup_at": _pickup(), **extra}
    return await client.post(ORDERS, json=body, headers=auth_headers(token))


async def _add_rule(client: AsyncClient, token: str, **over):
    today = _vn_today()
    body = {
        "type": "surcharge", "value_type": "percent", "value": 20, "name": "Phụ thu Tết",
        "start_date": (today - timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
    }
    body.update(over)
    return await client.post(RULES, json=body, headers=auth_headers(token))


async def test_manual_percent_surcharge_and_fixed_discount(client: AsyncClient, actx: dict):
    """Ví dụ chuẩn: subtotal 200k, phụ thu 10% (=20k), giảm cố định 15k → total 205k."""
    r = await _create(
        client, actx["staff_token"],
        surcharge={"value_type": "percent", "value": 10, "reason": "Phụ thu cuối tuần"},
        discount={"value_type": "fixed", "value": 15000, "reason": "Khách quen"},
    )
    assert r.status_code == 201, r.text
    o = r.json()
    assert _num(o["subtotal"]) == 200000
    assert _num(o["surcharge_amount"]) == 20000
    assert _num(o["discount_amount"]) == 15000
    assert _num(o["total_amount"]) == 205000
    assert o["surcharge_reason"] == "Phụ thu cuối tuần"
    assert o["discount_reason"] == "Khách quen"


async def test_percent_discount(client: AsyncClient, actx: dict):
    r = await _create(client, actx["staff_token"],
                      discount={"value_type": "percent", "value": 25})
    o = r.json()
    assert _num(o["discount_amount"]) == 50000  # 25% of 200k
    assert _num(o["total_amount"]) == 150000


async def test_discount_clamped_so_total_not_negative(client: AsyncClient, actx: dict):
    r = await _create(client, actx["staff_token"],
                      discount={"value_type": "fixed", "value": 999999})
    o = r.json()
    assert _num(o["discount_amount"]) == 200000  # clamp về subtotal (+0 phụ thu)
    assert _num(o["total_amount"]) == 0


async def test_no_adjustment_defaults_zero(client: AsyncClient, actx: dict):
    r = await _create(client, actx["staff_token"])
    o = r.json()
    assert _num(o["subtotal"]) == 200000
    assert _num(o["surcharge_amount"]) == 0
    assert _num(o["discount_amount"]) == 0
    assert _num(o["total_amount"]) == 200000
    assert o["surcharge_reason"] is None and o["discount_reason"] is None


async def test_auto_apply_rule_when_no_manual(client: AsyncClient, actx: dict):
    await _add_rule(client, actx["owner_token"], type="surcharge", value=20)
    r = await _create(client, actx["staff_token"])
    o = r.json()
    assert _num(o["surcharge_amount"]) == 40000  # 20% tự áp
    assert o["surcharge_reason"] == "Phụ thu Tết"
    assert _num(o["total_amount"]) == 240000


async def test_manual_overrides_rule(client: AsyncClient, actx: dict):
    await _add_rule(client, actx["owner_token"], type="surcharge", value=20)
    r = await _create(client, actx["staff_token"],
                      surcharge={"value_type": "fixed", "value": 5000, "reason": "tay"})
    o = r.json()
    assert _num(o["surcharge_amount"]) == 5000
    assert o["surcharge_reason"] == "tay"


async def test_rule_out_of_range_not_applied(client: AsyncClient, actx: dict):
    today = _vn_today()
    await _add_rule(client, actx["owner_token"], type="surcharge", value=20, name="old",
                    start_date=(today - timedelta(days=10)).isoformat(),
                    end_date=(today - timedelta(days=5)).isoformat())
    r = await _create(client, actx["staff_token"])
    assert _num(r.json()["surcharge_amount"]) == 0


async def test_snapshot_immutable_after_rule_change(client: AsyncClient, actx: dict):
    rule = await _add_rule(client, actx["owner_token"], type="discount",
                           value_type="percent", value=10, name="KM")
    rid = rule.json()["id"]
    r = await _create(client, actx["staff_token"])
    oid = r.json()["id"]
    assert _num(r.json()["discount_amount"]) == 20000  # 10% of 200k
    # đổi rule → đơn cũ KHÔNG đổi.
    await client.put(f"{RULES}/{rid}", json={"value": 50}, headers=auth_headers(actx["owner_token"]))
    again = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(actx["staff_token"]))
    assert _num(again.json()["discount_amount"]) == 20000


async def test_reconciliation_with_adjustments(client: AsyncClient, actx: dict):
    """Đơn có phụ thu + giảm → total thật; thu đủ tiền mặt → đóng ca KHỚP."""
    r = await _create(
        client, actx["staff_token"],
        surcharge={"value_type": "percent", "value": 10},
        discount={"value_type": "fixed", "value": 15000},
    )
    o = r.json()
    total = _num(o["total_amount"])
    assert total == 205000

    pay = await client.post("/api/v1/payments", json={
        "order_id": o["id"], "amount": total,
        "payment_method": "cash", "transaction_type": "payment",
    }, headers=auth_headers(actx["staff_token"]))
    assert pay.status_code == 201, pay.text

    cur = await client.get("/api/v1/shifts/current", headers=auth_headers(actx["staff_token"]))
    sid = cur.json()["id"]
    close = await client.post(f"/api/v1/shifts/{sid}/close",
                              json={"closing_cash_actual": 100000 + total},
                              headers=auth_headers(actx["staff_token"]))
    assert close.status_code == 200, close.text
    b = close.json()
    assert _num(b["total_cash"]) == total
    assert _num(b["closing_cash_expected"]) == 100000 + total
    assert _num(b["cash_difference"]) == 0
