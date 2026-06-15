"""Test báo cáo giảm giá theo nhân viên (Stage 5.4). Viết TRƯỚC (TDD).

Mỗi đơn có discount > 0 ghi discount_logs (ai giảm / số tiền / lý do). Báo cáo
GET /reports/discounts (owner): tổng giảm + theo nhân viên, lọc theo khoảng ngày.
"""
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import auth_headers, login

ORDERS = "/api/v1/orders"
REPORT = "/api/v1/reports/discounts"


def _num(x) -> int:
    return int(Decimal(str(x)))


def _pickup(h: float = 4) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=h)).isoformat()


ITEMS = [{"service_name": "Giặt", "quantity": 1, "unit_price": 100000}]


@pytest_asyncio.fixture
async def dctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"},
                          headers=auth_headers(owner_token))
    branch = r.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000053", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    staff_token = await login(client, "0900000053", "pass123")
    return {"owner": owner, "owner_token": owner_token, "staff_token": staff_token, "branch": branch}


async def _create(client: AsyncClient, token: str, **extra):
    return await client.post(ORDERS, json={"items": ITEMS, "pickup_at": _pickup(), **extra},
                             headers=auth_headers(token))


async def test_discount_report_by_staff(client: AsyncClient, dctx: dict):
    # NV A: 2 đơn giảm (10k + 5k). Owner: 1 đơn giảm 20k. 1 đơn không giảm → bỏ.
    await _create(client, dctx["staff_token"], discount={"value_type": "fixed", "value": 10000, "reason": "a"})
    await _create(client, dctx["staff_token"], discount={"value_type": "fixed", "value": 5000, "reason": "b"})
    await _create(client, dctx["owner_token"], branch_id=dctx["branch"]["id"],
                  discount={"value_type": "fixed", "value": 20000})
    await _create(client, dctx["staff_token"])  # không giảm

    r = await client.get(REPORT, headers=auth_headers(dctx["owner_token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert _num(data["total_discount"]) == 35000
    assert data["order_count"] == 3
    rows = {row["user_name"]: row for row in data["rows"]}
    assert _num(rows["NV A"]["total_discount"]) == 15000
    assert rows["NV A"]["order_count"] == 2


async def test_discount_report_date_filter(client: AsyncClient, dctx: dict):
    await _create(client, dctx["staff_token"], discount={"value_type": "fixed", "value": 10000})
    # Lọc từ NGÀY MAI → không có log nào.
    future = (datetime.now(timezone.utc) + timedelta(days=1)).date().isoformat()
    empty = await client.get(f"{REPORT}?start_date={future}", headers=auth_headers(dctx["owner_token"]))
    assert empty.status_code == 200
    assert _num(empty.json()["total_discount"]) == 0
    assert empty.json()["rows"] == []


async def test_discount_report_owner_only(client: AsyncClient, dctx: dict):
    bad = await client.get(REPORT, headers=auth_headers(dctx["staff_token"]))
    assert bad.status_code == 403
