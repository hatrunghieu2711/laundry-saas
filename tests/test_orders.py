"""Test order service: tạo đơn + items, order_code, transition trạng thái,
khóa sửa khi có payment, cancel, cách ly tenant. Viết TRƯỚC service (TDD)."""
import uuid
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from app.models.customer import Customer
from app.models.payment import Payment
from tests.conftest import auth_headers, login

ORDERS = "/api/v1/orders"


def _num(x) -> int:
    return int(Decimal(str(x)))


@pytest_asyncio.fixture
async def octx(client: AsyncClient, owner: dict) -> dict:
    """Owner + 2 branch + staff ở branch A."""
    owner_token = await login(client, owner["phone"], owner["password"])

    async def _branch(name: str) -> dict:
        r = await client.post("/api/v1/branches", json={"name": name},
                              headers=auth_headers(owner_token))
        assert r.status_code == 201, r.text
        return r.json()

    branch_a = await _branch("CN A")
    branch_b = await _branch("CN B")
    r = await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000041", "password": "pass123",
              "role": "staff", "branch_id": branch_a["id"]},
        headers=auth_headers(owner_token),
    )
    assert r.status_code == 201, r.text
    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_token": await login(client, "0900000041", "pass123"),
        "branch_a": branch_a,
        "branch_b": branch_b,
    }


async def _create_order(client: AsyncClient, token: str, items: list[dict], **extra) -> dict:
    body = {"items": items, **extra}
    return await client.post(ORDERS, json=body, headers=auth_headers(token))


_ITEMS = [
    {"service_name": "Giặt thường", "quantity": 2, "unit_price": 30000},
    {"service_name": "Giặt khô", "quantity": 1, "unit_price": 50000},
]


async def _open_shift(client: AsyncClient, token: str) -> str:
    r = await client.post("/api/v1/shifts/open", json={"opening_cash": 0},
                          headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _insert_payment(octx: dict, shift_id: str, order_id: str, amount: int) -> None:
    async with SessionFactory() as db:
        db.add(Payment(
            tenant_id=octx["owner"]["tenant_id"],
            branch_id=uuid.UUID(octx["branch_a"]["id"]),
            order_id=uuid.UUID(order_id),
            shift_id=uuid.UUID(shift_id),
            amount=Decimal(amount),
            payment_method="cash",
            transaction_type="payment",
            created_by=octx["owner"]["user_id"],
        ))
        await db.commit()


async def _log_count(order_id: str) -> int:
    async with SessionFactory() as db:
        return await db.scalar(
            text("SELECT count(*) FROM order_tracking_logs WHERE order_id=:i"),
            {"i": order_id},
        )


async def _set_status(client: AsyncClient, token: str, oid: str, status: str):
    return await client.patch(f"{ORDERS}/{oid}/status", json={"order_status": status},
                              headers=auth_headers(token))


# ── tạo đơn ─────────────────────────────────────────────────────────────────
async def test_create_order_code_total_and_log(client: AsyncClient, octx: dict):
    r1 = await _create_order(client, octx["staff_token"], _ITEMS)
    assert r1.status_code == 201, r1.text
    b1 = r1.json()
    assert b1["order_code"] == "B1-00001"
    assert b1["order_status"] == "created"
    assert b1["payment_status"] == "unpaid"
    assert _num(b1["total_amount"]) == 110000  # 2*30000 + 1*50000
    assert len(b1["items"]) == 2
    assert b1["created_by_name"] == "NV A"  # tên người tạo nhúng sẵn

    # order_code tuần tự.
    r2 = await _create_order(client, octx["staff_token"], _ITEMS)
    assert r2.json()["order_code"] == "B1-00002"

    # tracking log dòng đầu = 'created'.
    assert await _log_count(b1["id"]) == 1


async def test_total_ignores_client_quantity_decimal(client: AsyncClient, octx: dict):
    items = [{"service_name": "Giặt kg", "quantity": 1.5, "unit_price": 20000}]
    r = await _create_order(client, octx["staff_token"], items)
    assert r.status_code == 201, r.text
    assert _num(r.json()["total_amount"]) == 30000  # 1.5 * 20000


# ── transition trạng thái ───────────────────────────────────────────────────
async def test_status_full_forward_flow(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered", "completed"]:
        resp = await _set_status(client, octx["staff_token"], oid, st)
        assert resp.status_code == 200, resp.text
        assert resp.json()["order_status"] == st
    # 1 (created) + 5 transition = 6 dòng log.
    assert await _log_count(oid) == 6


async def test_status_backward_forbidden(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered"]:
        await _set_status(client, octx["staff_token"], oid, st)
    resp = await _set_status(client, octx["staff_token"], oid, "washing")
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


async def test_status_skip_forward_forbidden(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    resp = await _set_status(client, octx["staff_token"], oid, "ready")  # created -> ready
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


async def test_completed_is_terminal(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered", "completed"]:
        await _set_status(client, octx["staff_token"], oid, st)
    resp = await _set_status(client, octx["staff_token"], oid, "washing")
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


# ── cancel (soft delete) ────────────────────────────────────────────────────
async def test_cancel_from_created(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    resp = await client.delete(f"{ORDERS}/{oid}", headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 200
    assert resp.json()["order_status"] == "cancelled"
    # Không xóa cứng.
    async with SessionFactory() as db:
        still = await db.scalar(text("SELECT count(*) FROM orders WHERE id=:i"), {"i": oid})
        assert still == 1


async def test_cancel_after_delivered_forbidden(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered"]:
        await _set_status(client, octx["staff_token"], oid, st)
    resp = await client.delete(f"{ORDERS}/{oid}", headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


# ── không sửa total khi đã có payment ───────────────────────────────────────
async def test_cannot_change_total_with_payment(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    sid = await _open_shift(client, octx["staff_token"])
    await _insert_payment(octx, sid, oid, 50000)

    resp = await client.put(f"{ORDERS}/{oid}", json={"total_amount": 999},
                            headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 409
    assert resp.json()["code"] == "ORDER_HAS_PAYMENT"

    # Thêm item cũng bị chặn khi đã có payment.
    add = await client.post(f"{ORDERS}/{oid}/items",
                            json={"service_name": "X", "quantity": 1, "unit_price": 1000},
                            headers=auth_headers(octx["staff_token"]))
    assert add.status_code == 409
    assert add.json()["code"] == "ORDER_HAS_PAYMENT"


async def test_put_notes_and_customer(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    async with SessionFactory() as db:
        cust = Customer(tenant_id=octx["owner"]["tenant_id"], full_name="Chị Lan")
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    resp = await client.put(f"{ORDERS}/{oid}",
                            json={"notes": "Giao gấp", "customer_id": cust_id},
                            headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["notes"] == "Giao gấp"
    assert resp.json()["customer_id"] == cust_id


# ── items CRUD + recompute ──────────────────────────────────────────────────
async def test_items_crud_recompute_total(client: AsyncClient, octx: dict):
    created = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    oid = created["id"]

    add = await client.post(f"{ORDERS}/{oid}/items",
                            json={"service_name": "Sấy", "quantity": 1, "unit_price": 40000},
                            headers=auth_headers(octx["staff_token"]))
    assert add.status_code == 201, add.text
    assert _num(add.json()["total_amount"]) == 150000  # 110000 + 40000
    item_id = next(i["id"] for i in add.json()["items"] if i["service_name"] == "Sấy")

    upd = await client.put(f"{ORDERS}/{oid}/items/{item_id}",
                           json={"service_name": "Sấy", "quantity": 2, "unit_price": 40000},
                           headers=auth_headers(octx["staff_token"]))
    assert upd.status_code == 200, upd.text
    assert _num(upd.json()["total_amount"]) == 190000  # 110000 + 80000

    dele = await client.delete(f"{ORDERS}/{oid}/items/{item_id}",
                               headers=auth_headers(octx["staff_token"]))
    assert dele.status_code == 200, dele.text
    assert _num(dele.json()["total_amount"]) == 110000


async def test_items_locked_when_ready(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, octx["staff_token"], oid, st)
    resp = await client.post(f"{ORDERS}/{oid}/items",
                             json={"service_name": "X", "quantity": 1, "unit_price": 1000},
                             headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 409
    assert resp.json()["code"] == "ORDER_ITEMS_LOCKED"


# ── GET by id / code / list ─────────────────────────────────────────────────
async def test_get_by_id_and_code(client: AsyncClient, octx: dict):
    created = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    oid, code = created["id"], created["order_code"]

    by_id = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(octx["staff_token"]))
    assert by_id.status_code == 200 and by_id.json()["id"] == oid

    by_code = await client.get(f"{ORDERS}/code/{code}", headers=auth_headers(octx["staff_token"]))
    assert by_code.status_code == 200 and by_code.json()["id"] == oid


async def test_list_filter_and_pagination(client: AsyncClient, octx: dict):
    o1 = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    await _create_order(client, octx["staff_token"], _ITEMS)
    await _set_status(client, octx["staff_token"], o1["id"], "washing")

    # filter order_status=washing -> chỉ 1.
    f = await client.get(f"{ORDERS}?order_status=washing", headers=auth_headers(octx["staff_token"]))
    assert f.status_code == 200
    assert f.json()["total"] == 1

    # pagination limit.
    p = await client.get(f"{ORDERS}?limit=1", headers=auth_headers(octx["staff_token"]))
    assert p.json()["total"] == 2 and len(p.json()["items"]) == 1


# ── cách ly tenant ──────────────────────────────────────────────────────────
async def test_cross_tenant_isolation(client: AsyncClient, octx: dict, owner2: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    other = await login(client, owner2["phone"], owner2["password"])
    got = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(other))
    assert got.status_code == 404
    assert got.json()["code"] == "ORDER_NOT_FOUND"
    lst = await client.get(ORDERS, headers=auth_headers(other))
    assert lst.status_code == 200 and lst.json()["total"] == 0
