"""Test price_rules: CRUD owner + áp dụng theo ngày (Stage 5.4). Viết TRƯỚC (TDD).

Quy tắc tự áp khi tạo đơn (xem test_order_adjustments). Ở đây test:
- owner CRUD; staff KHÔNG ghi được.
- validate khoảng ngày (end >= start).
- GET /price-rules/applicable trả rule surcharge + discount đang hiệu lực HÔM NAY
  (giờ VN), bỏ rule ngoài khoảng / đã ẩn.
"""
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import auth_headers, login

RULES = "/api/v1/price-rules"


def _vn_today():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date()


def _rule_body(**over) -> dict:
    today = _vn_today()
    body = {
        "type": "surcharge",
        "value_type": "percent",
        "value": 20,
        "name": "Phụ thu Tết",
        "start_date": (today - timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
    }
    body.update(over)
    return body


@pytest_asyncio.fixture
async def rctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"},
                          headers=auth_headers(owner_token))
    branch = r.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000051", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    staff_token = await login(client, "0900000051", "pass123")
    return {"owner": owner, "owner_token": owner_token, "staff_token": staff_token, "branch": branch}


async def test_owner_crud_rule(client: AsyncClient, rctx: dict):
    t = rctx["owner_token"]
    r = await client.post(RULES, json=_rule_body(), headers=auth_headers(t))
    assert r.status_code == 201, r.text
    rule = r.json()
    rid = rule["id"]
    assert rule["type"] == "surcharge" and rule["value_type"] == "percent"
    assert rule["is_active"] is True

    lst = await client.get(RULES, headers=auth_headers(t))
    assert lst.status_code == 200
    assert any(x["id"] == rid for x in lst.json()["items"])

    up = await client.put(f"{RULES}/{rid}", json={"value": 10, "name": "Phụ thu lễ"},
                          headers=auth_headers(t))
    assert up.status_code == 200
    assert int(float(up.json()["value"])) == 10
    assert up.json()["name"] == "Phụ thu lễ"

    d = await client.delete(f"{RULES}/{rid}", headers=auth_headers(t))
    assert d.status_code == 200
    assert d.json()["is_active"] is False


async def test_staff_cannot_write_rule(client: AsyncClient, rctx: dict):
    bad = await client.post(RULES, json=_rule_body(), headers=auth_headers(rctx["staff_token"]))
    assert bad.status_code == 403


async def test_invalid_date_range(client: AsyncClient, rctx: dict):
    today = _vn_today()
    body = _rule_body(start_date=today.isoformat(),
                      end_date=(today - timedelta(days=2)).isoformat())
    r = await client.post(RULES, json=body, headers=auth_headers(rctx["owner_token"]))
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_DATE_RANGE"


async def test_applicable_today(client: AsyncClient, rctx: dict):
    t = rctx["owner_token"]
    today = _vn_today()
    await client.post(RULES, json=_rule_body(type="surcharge", value=20),
                      headers=auth_headers(t))
    await client.post(RULES, json=_rule_body(type="discount", value_type="fixed",
                      value=10000, name="Giảm khai trương"), headers=auth_headers(t))
    # rule quá khứ — KHÔNG áp.
    await client.post(RULES, json=_rule_body(
        type="surcharge", value=99, name="cũ",
        start_date=(today - timedelta(days=10)).isoformat(),
        end_date=(today - timedelta(days=5)).isoformat()), headers=auth_headers(t))

    # staff đọc được applicable (để POS điền sẵn).
    appl = await client.get(f"{RULES}/applicable", headers=auth_headers(rctx["staff_token"]))
    assert appl.status_code == 200, appl.text
    data = appl.json()
    assert data["surcharge"] is not None and int(float(data["surcharge"]["value"])) == 20
    assert data["discount"] is not None and data["discount"]["value_type"] == "fixed"


async def test_applicable_none_when_no_rule(client: AsyncClient, rctx: dict):
    appl = await client.get(f"{RULES}/applicable", headers=auth_headers(rctx["owner_token"]))
    assert appl.status_code == 200
    assert appl.json()["surcharge"] is None
    assert appl.json()["discount"] is None


async def test_rule_tenant_isolation(client: AsyncClient, rctx: dict, owner2: dict):
    await client.post(RULES, json=_rule_body(), headers=auth_headers(rctx["owner_token"]))
    t2 = await login(client, owner2["phone"], owner2["password"])
    appl = await client.get(f"{RULES}/applicable", headers=auth_headers(t2))
    assert appl.json()["surcharge"] is None  # tenant 2 không thấy rule tenant 1
