"""Test bảng giá dịch vụ động (services) + tính tiền per_unit / tier +
snapshot giá giữ nguyên khi bảng giá đổi + cách ly tenant. Viết TRƯỚC service (TDD).

Bảng giá Giặt Ủi 2H (tier): ≤3kg=60k, 5kg=90k, 7kg=120k, >7kg=18k/kg.
Đồ lẻ (per_unit): vd Áo Vest 60k/cái.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from tests.conftest import auth_headers, login

SERVICES = "/api/v1/services"
ORDERS = "/api/v1/orders"


def _num(x) -> int:
    return int(Decimal(str(x)))


def _pickup() -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=4)).isoformat()


# Bảng giá giặt sấy theo bậc cân (đúng Giặt Ủi 2H).
_GIAT_SAY_TIERS = [
    {"label": "≤3kg", "max_value": 3, "price": 60000, "per_unit": False},
    {"label": "5kg", "max_value": 5, "price": 90000, "per_unit": False},
    {"label": "7kg", "max_value": 7, "price": 120000, "per_unit": False},
    {"label": ">7kg", "max_value": None, "price": 18000, "per_unit": True},
]


@pytest_asyncio.fixture
async def sctx(client: AsyncClient, owner: dict) -> dict:
    """Owner + 1 branch + 1 staff branch A — để tạo đơn tham chiếu service."""
    owner_token = await login(client, owner["phone"], owner["password"])
    rb = await client.post("/api/v1/branches", json={"name": "CN A"},
                           headers=auth_headers(owner_token))
    assert rb.status_code == 201, rb.text
    branch_a = rb.json()
    ru = await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000051", "password": "pass123",
              "role": "staff", "branch_id": branch_a["id"]},
        headers=auth_headers(owner_token),
    )
    assert ru.status_code == 201, ru.text
    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_token": await login(client, "0900000051", "pass123"),
        "branch_a": branch_a,
    }


async def _create_service(client: AsyncClient, token: str, **body) -> dict:
    return await client.post(SERVICES, json=body, headers=auth_headers(token))


async def _giat_say(client: AsyncClient, token: str) -> dict:
    r = await _create_service(
        client, token, name="Giặt sấy", unit="kg", pricing_type="tier",
        display_order=1, tiers=_GIAT_SAY_TIERS,
    )
    assert r.status_code == 201, r.text
    return r.json()


async def _ao_vest(client: AsyncClient, token: str) -> dict:
    r = await _create_service(
        client, token, name="Áo Vest", unit="cai", pricing_type="per_unit",
        unit_price=60000, display_order=2,
    )
    assert r.status_code == 201, r.text
    return r.json()


# ── CRUD service ─────────────────────────────────────────────────────────────
async def test_create_per_unit_service(client: AsyncClient, sctx: dict):
    svc = await _ao_vest(client, sctx["owner_token"])
    assert svc["name"] == "Áo Vest"
    assert svc["unit"] == "cai"
    assert svc["pricing_type"] == "per_unit"
    assert _num(svc["unit_price"]) == 60000
    assert svc["is_active"] is True
    assert svc["tiers"] == []


async def test_create_tier_service(client: AsyncClient, sctx: dict):
    svc = await _giat_say(client, sctx["owner_token"])
    assert svc["pricing_type"] == "tier"
    assert len(svc["tiers"]) == 4
    assert _num(svc["tiers"][0]["price"]) == 60000
    assert svc["tiers"][0]["label"] == "≤3kg"
    assert svc["tiers"][-1]["max_value"] is None
    assert svc["tiers"][-1]["per_unit"] is True


async def test_tier_service_requires_tiers(client: AsyncClient, sctx: dict):
    r = await _create_service(client, sctx["owner_token"], name="X", unit="kg",
                              pricing_type="tier", tiers=[])
    assert r.status_code == 422


async def test_staff_cannot_write_can_read(client: AsyncClient, sctx: dict):
    # staff không tạo được.
    r = await _create_service(client, sctx["staff_token"], name="X", unit="cai",
                              pricing_type="per_unit", unit_price=1000)
    assert r.status_code == 403
    # nhưng đọc được.
    await _ao_vest(client, sctx["owner_token"])
    lst = await client.get(SERVICES, headers=auth_headers(sctx["staff_token"]))
    assert lst.status_code == 200
    assert lst.json()["total"] == 1


async def test_service_category_and_favorite(client: AsyncClient, sctx: dict):
    r = await _create_service(
        client, sctx["owner_token"], name="Áo sơ mi", unit="cai",
        pricing_type="per_unit", unit_price=15000, category="Đồ lẻ", is_favorite=True,
    )
    assert r.status_code == 201, r.text
    svc = r.json()
    assert svc["category"] == "Đồ lẻ"
    assert svc["is_favorite"] is True

    # mặc định khi không gửi: category None, is_favorite False.
    plain = await _ao_vest(client, sctx["owner_token"])
    assert plain["category"] is None
    assert plain["is_favorite"] is False

    # toggle favorite qua PUT.
    upd = await client.put(f"{SERVICES}/{plain['id']}", json={"is_favorite": True},
                           headers=auth_headers(sctx["owner_token"]))
    assert upd.status_code == 200, upd.text
    assert upd.json()["is_favorite"] is True


async def test_update_and_soft_delete_service(client: AsyncClient, sctx: dict):
    svc = await _ao_vest(client, sctx["owner_token"])
    upd = await client.put(f"{SERVICES}/{svc['id']}", json={"unit_price": 70000},
                           headers=auth_headers(sctx["owner_token"]))
    assert upd.status_code == 200, upd.text
    assert _num(upd.json()["unit_price"]) == 70000

    # soft delete -> is_active=false, không xóa cứng.
    dele = await client.delete(f"{SERVICES}/{svc['id']}",
                               headers=auth_headers(sctx["owner_token"]))
    assert dele.status_code == 200
    assert dele.json()["is_active"] is False
    async with SessionFactory() as db:
        n = await db.scalar(text("SELECT count(*) FROM services WHERE id=:i"),
                            {"i": svc["id"]})
        assert n == 1

    # mặc định list chỉ trả active.
    lst = await client.get(SERVICES, headers=auth_headers(sctx["owner_token"]))
    assert lst.json()["total"] == 0
    # include_inactive=true thấy lại.
    lst2 = await client.get(f"{SERVICES}?include_inactive=true",
                            headers=auth_headers(sctx["owner_token"]))
    assert lst2.json()["total"] == 1


async def test_list_ordered_by_display_order(client: AsyncClient, sctx: dict):
    await _giat_say(client, sctx["owner_token"])   # display_order 1
    await _ao_vest(client, sctx["owner_token"])    # display_order 2
    lst = await client.get(SERVICES, headers=auth_headers(sctx["owner_token"]))
    names = [s["name"] for s in lst.json()["items"]]
    assert names == ["Giặt sấy", "Áo Vest"]


# ── tính tiền per_unit ───────────────────────────────────────────────────────
async def test_order_per_unit_pricing_snapshot(client: AsyncClient, sctx: dict):
    svc = await _ao_vest(client, sctx["owner_token"])
    r = await client.post(ORDERS, json={"items": [
        {"service_id": svc["id"], "quantity": 2},
    ], "pickup_at": _pickup()}, headers=auth_headers(sctx["staff_token"]))
    assert r.status_code == 201, r.text
    item = r.json()["items"][0]
    assert item["service_id"] == svc["id"]
    assert item["service_name"] == "Áo Vest"          # snapshot tên
    assert _num(item["unit_price"]) == 60000
    assert _num(item["subtotal"]) == 120000           # 2 × 60000
    assert _num(r.json()["total_amount"]) == 120000


# ── tính tiền tier (bậc cân) ─────────────────────────────────────────────────
async def test_order_tier_pricing_flat_brackets(client: AsyncClient, sctx: dict):
    svc = await _giat_say(client, sctx["owner_token"])

    async def _price(qty) -> dict:
        r = await client.post(ORDERS, json={"items": [
            {"service_id": svc["id"], "quantity": qty},
        ], "pickup_at": _pickup()}, headers=auth_headers(sctx["staff_token"]))
        assert r.status_code == 201, r.text
        return r.json()["items"][0]

    # ≤3kg trọn gói 60k (KHÔNG nhân theo cân).
    i = await _price(2.5)
    assert _num(i["subtotal"]) == 60000
    assert i["service_name"] == "Giặt sấy (≤3kg)"
    # đúng 3kg vẫn bậc ≤3kg.
    assert _num((await _price(3))["subtotal"]) == 60000
    # 4kg -> bậc 5kg = 90k.
    assert _num((await _price(4))["subtotal"]) == 90000
    # 6kg -> bậc 7kg = 120k.
    i6 = await _price(6)
    assert _num(i6["subtotal"]) == 120000
    assert i6["service_name"] == "Giặt sấy (7kg)"


async def test_order_tier_pricing_overflow_per_kg(client: AsyncClient, sctx: dict):
    svc = await _giat_say(client, sctx["owner_token"])
    r = await client.post(ORDERS, json={"items": [
        {"service_id": svc["id"], "quantity": 10},   # >7kg -> 18k/kg
    ], "pickup_at": _pickup()}, headers=auth_headers(sctx["staff_token"]))
    assert r.status_code == 201, r.text
    item = r.json()["items"][0]
    assert _num(item["unit_price"]) == 18000
    assert _num(item["subtotal"]) == 180000          # 10 × 18000
    assert item["service_name"] == "Giặt sấy (>7kg)"


# ── snapshot giá giữ nguyên khi bảng giá đổi ─────────────────────────────────
async def test_price_snapshot_immune_to_pricetable_change(client: AsyncClient, sctx: dict):
    svc = await _ao_vest(client, sctx["owner_token"])
    r = await client.post(ORDERS, json={"items": [
        {"service_id": svc["id"], "quantity": 1},
    ], "pickup_at": _pickup()}, headers=auth_headers(sctx["staff_token"]))
    oid = r.json()["id"]
    assert _num(r.json()["items"][0]["unit_price"]) == 60000

    # Đổi bảng giá: 60k -> 99k.
    upd = await client.put(f"{SERVICES}/{svc['id']}", json={"unit_price": 99000},
                           headers=auth_headers(sctx["owner_token"]))
    assert upd.status_code == 200

    # Đơn cũ vẫn giữ giá snapshot 60k.
    got = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(sctx["staff_token"]))
    assert _num(got.json()["items"][0]["unit_price"]) == 60000
    assert _num(got.json()["total_amount"]) == 60000


# ── đơn không có service_id vẫn chạy (manual line, backward compat) ──────────
async def test_order_manual_line_without_service(client: AsyncClient, sctx: dict):
    r = await client.post(ORDERS, json={"items": [
        {"service_name": "Hấp tẩy ố", "quantity": 1, "unit_price": 45000},
    ], "pickup_at": _pickup()}, headers=auth_headers(sctx["staff_token"]))
    assert r.status_code == 201, r.text
    item = r.json()["items"][0]
    assert item["service_id"] is None
    assert _num(item["subtotal"]) == 45000


# ── cách ly tenant ───────────────────────────────────────────────────────────
async def test_service_tenant_isolation(client: AsyncClient, sctx: dict, owner2: dict):
    svc = await _ao_vest(client, sctx["owner_token"])
    other = await login(client, owner2["phone"], owner2["password"])

    # owner2 không thấy service của tenant 1.
    lst = await client.get(SERVICES, headers=auth_headers(other))
    assert lst.status_code == 200 and lst.json()["total"] == 0
    got = await client.get(f"{SERVICES}/{svc['id']}", headers=auth_headers(other))
    assert got.status_code == 404

    # owner2 tạo branch + đơn, không reference được service tenant 1.
    rb = await client.post("/api/v1/branches", json={"name": "CN khác"},
                           headers=auth_headers(other))
    branch = rb.json()
    ro = await client.post(ORDERS, json={
        "branch_id": branch["id"],
        "items": [{"service_id": svc["id"], "quantity": 1}],
        "pickup_at": _pickup(),
    }, headers=auth_headers(other))
    assert ro.status_code == 404
    assert ro.json()["code"] == "SERVICE_NOT_FOUND"
