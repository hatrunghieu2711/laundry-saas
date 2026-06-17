"""Test order service: tạo đơn + items, order_code, transition trạng thái,
khóa sửa khi có payment, cancel, cách ly tenant. Viết TRƯỚC service (TDD)."""
import uuid
from datetime import datetime, timedelta, timezone
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


def _pickup(hours: float = 4) -> str:
    """ISO giờ hẹn giao ở tương lai (mặc định +4h)."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


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
    extra.setdefault("pickup_at", _pickup())
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
    assert resp.json()["code"] == "ORDER_CLOSED"


# ── Stage 3.9: lùi trạng thái có kiểm soát ──────────────────────────────────
async def test_revert_within_processing_group(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, t, oid, st)
    # lùi từng bước ready->drying->washing->created
    for st in ["drying", "washing", "created"]:
        r = await _set_status(client, t, oid, st)
        assert r.status_code == 200, r.text
        assert r.json()["order_status"] == st


async def test_revert_multistep_back_allowed(client: AsyncClient, octx: dict):
    # Lùi nhiều bước một lần trong nhóm xử lý: ready -> created.
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, t, oid, st)
    r = await _set_status(client, t, oid, "created")
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "created"


async def test_revert_delivered_unpaid_ok(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered"]:
        await _set_status(client, t, oid, st)
    r = await _set_status(client, t, oid, "ready")  # delivered chưa thu -> lùi OK
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "ready"


async def test_revert_delivered_paid_blocked(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered"]:
        await _set_status(client, t, oid, st)
    for ps in ["paid", "partial", "debt"]:
        await _set_order_db(oid, payment_status=ps)
        r = await _set_status(client, t, oid, "ready")
        assert r.status_code == 409, f"{ps}: {r.text}"
        assert r.json()["code"] == "CANNOT_REVERT_PAID_DELIVERY"


async def test_revert_completed_locked(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered", "completed"]:
        await _set_status(client, t, oid, st)
    r = await _set_status(client, t, oid, "ready")
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_CLOSED"


async def test_revert_cancelled_locked(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await client.delete(f"{ORDERS}/{oid}", headers=auth_headers(t))  # -> cancelled
    r = await _set_status(client, t, oid, "created")
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_CLOSED"


async def test_revert_writes_tracking_log(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying"]:
        await _set_status(client, t, oid, st)
    before = await _log_count(oid)  # created+washing+drying = 3
    await _set_status(client, t, oid, "washing")  # lùi drying->washing
    assert await _log_count(oid) == before + 1
    # dòng log mới nhất = 'washing', có changed_by
    async with SessionFactory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT status, changed_by FROM order_tracking_logs "
                    "WHERE order_id=:i ORDER BY created_at DESC LIMIT 1"
                ),
                {"i": oid},
            )
        ).first()
    assert row[0] == "washing"
    assert row[1] is not None


# ── Stage 3.9: search q (mã đơn HOẶC tên khách) ─────────────────────────────
async def test_list_search_q_by_code_and_name(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    # đơn 1: gắn khách tên "Nguyễn Văn An"
    async with SessionFactory() as db:
        cust = Customer(tenant_id=octx["owner"]["tenant_id"], full_name="Nguyễn Văn An")
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    o1 = (await _create_order(client, t, _ITEMS, customer_id=cust_id)).json()
    o2 = (await _create_order(client, t, _ITEMS)).json()  # khách lẻ

    # tìm theo mã đơn của o2
    r = await client.get(f"{ORDERS}?q={o2['order_code']}", headers=auth_headers(t))
    assert r.status_code == 200
    assert [o["id"] for o in r.json()["items"]] == [o2["id"]]

    # tìm theo tên khách gần đúng "văn an" (ILIKE, không phân biệt hoa thường)
    r = await client.get(f"{ORDERS}?q=văn an", headers=auth_headers(t))
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == o1["id"]


async def test_board_search_q(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    async with SessionFactory() as db:
        cust = Customer(tenant_id=octx["owner"]["tenant_id"], full_name="Trần Thị Bình")
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    o1 = (await _create_order(client, t, _ITEMS, customer_id=cust_id)).json()
    await _create_order(client, t, _ITEMS)  # khách lẻ

    r = await client.get(f"{ORDERS}/board?q=bình", headers=auth_headers(t))
    assert r.status_code == 200
    ids = [o["id"] for c in r.json()["columns"].values() for o in c]
    assert ids == [o1["id"]]
    assert r.json()["summary"]["total_orders"] == 1


# ── Stage 6.11: search q cũng match SĐT khách (tab Tra cứu) ──────────────────
async def test_list_search_q_by_phone(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    async with SessionFactory() as db:
        cust = Customer(
            tenant_id=octx["owner"]["tenant_id"],
            full_name="Lê Văn Cường",
            phone="0912345678",
        )
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    o1 = (await _create_order(client, t, _ITEMS, customer_id=cust_id)).json()
    await _create_order(client, t, _ITEMS)  # khách lẻ (không SĐT)

    # tìm theo phần SĐT (ILIKE substring)
    r = await client.get(f"{ORDERS}?q=12345", headers=auth_headers(t))
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == o1["id"]


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
    assert resp.json()["customer_name"] == "Chị Lan"  # tên khách nhúng sẵn


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


# ── Stage 3.7A: pickup_at (giờ hẹn giao) ────────────────────────────────────
async def _set_order_db(order_id: str, *, pickup_at=None, payment_status=None) -> None:
    async with SessionFactory() as db:
        if pickup_at is not None:
            await db.execute(text("UPDATE orders SET pickup_at=:p WHERE id=:i"),
                             {"p": pickup_at, "i": order_id})
        if payment_status is not None:
            await db.execute(text("UPDATE orders SET payment_status=:s WHERE id=:i"),
                             {"s": payment_status, "i": order_id})
        await db.commit()


async def test_pickup_at_required(client: AsyncClient, octx: dict):
    # Không gửi pickup_at -> 422 (field bắt buộc).
    r = await client.post(ORDERS, json={"items": _ITEMS},
                          headers=auth_headers(octx["staff_token"]))
    assert r.status_code == 422


async def test_pickup_at_in_past_rejected(client: AsyncClient, octx: dict):
    r = await client.post(ORDERS, json={"items": _ITEMS, "pickup_at": _pickup(-1)},
                          headers=auth_headers(octx["staff_token"]))
    assert r.status_code == 422
    assert r.json()["code"] == "PICKUP_AT_IN_PAST"


async def test_order_out_returns_pickup_at(client: AsyncClient, octx: dict):
    body = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    assert "pickup_at" in body and body["pickup_at"] is not None
    assert body["requires_payment"] is False


async def test_put_pickup_at_edit_and_lock(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    new_pickup = _pickup(10)
    r = await client.put(f"{ORDERS}/{oid}", json={"pickup_at": new_pickup},
                         headers=auth_headers(t))
    assert r.status_code == 200, r.text
    # so sánh theo mốc thời gian (chuẩn hóa khác biệt offset/định dạng).
    assert datetime.fromisoformat(r.json()["pickup_at"]) == datetime.fromisoformat(new_pickup)

    # đơn đã completed -> không sửa được giờ hẹn.
    for st in ["washing", "drying", "ready", "delivered", "completed"]:
        await _set_status(client, t, oid, st)
    blocked = await client.put(f"{ORDERS}/{oid}", json={"pickup_at": _pickup(20)},
                               headers=auth_headers(t))
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ORDER_CLOSED"


# ── Stage 3.7A: deliver còn nợ -> requires_payment ──────────────────────────
async def _advance_to_ready(client: AsyncClient, t: str, oid: str) -> None:
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, t, oid, st)


async def test_deliver_unpaid_sets_requires_payment(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_ready(client, t, oid)
    r = await _set_status(client, t, oid, "delivered")
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "delivered"
    assert r.json()["requires_payment"] is True


async def test_deliver_paid_no_requires_payment(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_ready(client, t, oid)
    await _set_order_db(oid, payment_status="paid")
    r = await _set_status(client, t, oid, "delivered")
    assert r.status_code == 200, r.text
    assert r.json()["requires_payment"] is False


async def test_deliver_debt_no_requires_payment(client: AsyncClient, octx: dict):
    # Giao-nợ có chủ đích (payment_status='debt') -> KHÔNG ép hỏi thanh toán.
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_ready(client, t, oid)
    await _set_order_db(oid, payment_status="debt")
    r = await _set_status(client, t, oid, "delivered")
    assert r.status_code == 200, r.text
    assert r.json()["requires_payment"] is False


# ── Stage 3.7A: dashboard vận hành (board) ──────────────────────────────────
async def test_board_grouping_overdue_and_summary(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    o_created = (await _create_order(client, t, _ITEMS)).json()
    o_wash = (await _create_order(client, t, _ITEMS)).json()
    await _set_status(client, t, o_wash["id"], "washing")
    o_overdue = (await _create_order(client, t, _ITEMS)).json()
    o_paid = (await _create_order(client, t, _ITEMS)).json()
    o_debt = (await _create_order(client, t, _ITEMS)).json()
    o_done = (await _create_order(client, t, _ITEMS)).json()
    o_cancel = (await _create_order(client, t, _ITEMS)).json()

    # quá giờ hẹn cho o_overdue; gán payment_status cho o_paid/o_debt.
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    await _set_order_db(o_overdue["id"], pickup_at=past)
    await _set_order_db(o_paid["id"], payment_status="paid")
    await _set_order_db(o_debt["id"], payment_status="debt")
    # o_done -> completed (ẩn khỏi board); o_cancel -> cancelled (ẩn).
    for st in ["washing", "drying", "ready", "delivered", "completed"]:
        await _set_status(client, t, o_done["id"], st)
    await client.delete(f"{ORDERS}/{o_cancel['id']}", headers=auth_headers(t))

    r = await client.get(f"{ORDERS}/board", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    board = r.json()
    cols = board["columns"]

    # nhóm đúng theo order_status; terminal bị ẩn.
    created_ids = {o["id"] for o in cols["created"]}
    assert created_ids == {o_created["id"], o_overdue["id"], o_paid["id"], o_debt["id"]}
    assert {o["id"] for o in cols["washing"]} == {o_wash["id"]}
    assert cols["drying"] == [] and cols["ready"] == [] and cols["delivered"] == []
    all_ids = {o["id"] for c in cols.values() for o in c}
    assert o_done["id"] not in all_ids and o_cancel["id"] not in all_ids

    # is_overdue: chỉ o_overdue.
    by_id = {o["id"]: o for c in cols.values() for o in c}
    assert by_id[o_overdue["id"]]["is_overdue"] is True
    assert by_id[o_created["id"]]["is_overdue"] is False

    # summary đếm đúng.
    s = board["summary"]
    assert s["total_orders"] == 5
    assert s["unpaid"] == 3   # o_created, o_wash, o_overdue
    assert s["paid"] == 1
    assert s["debt"] == 1
    assert s["overdue"] == 1


async def test_board_delivered_not_overdue(client: AsyncClient, octx: dict):
    # Đơn delivered dù quá giờ hẹn vẫn KHÔNG tính trễ (đã rời tiệm).
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready", "delivered"]:
        await _set_status(client, t, oid, st)
    await _set_order_db(oid, pickup_at=datetime.now(timezone.utc) - timedelta(hours=2))

    r = await client.get(f"{ORDERS}/board", headers=auth_headers(t))
    board = r.json()
    delivered = {o["id"]: o for o in board["columns"]["delivered"]}
    assert oid in delivered
    assert delivered[oid]["is_overdue"] is False
    assert board["summary"]["overdue"] == 0


async def test_board_tenant_isolation(client: AsyncClient, octx: dict, owner2: dict):
    await _create_order(client, octx["staff_token"], _ITEMS)
    other = await login(client, owner2["phone"], owner2["password"])
    r = await client.get(f"{ORDERS}/board", headers=auth_headers(other))
    assert r.status_code == 200
    assert r.json()["summary"]["total_orders"] == 0


# ── cách ly tenant ──────────────────────────────────────────────────────────
async def test_cross_tenant_isolation(client: AsyncClient, octx: dict, owner2: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    other = await login(client, owner2["phone"], owner2["password"])
    got = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(other))
    assert got.status_code == 404
    assert got.json()["code"] == "ORDER_NOT_FOUND"
    lst = await client.get(ORDERS, headers=auth_headers(other))
    assert lst.status_code == 200 and lst.json()["total"] == 0
