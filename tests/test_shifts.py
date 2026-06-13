"""Test shift service: mở/đóng ca + reconciliation + sign convention.

Viết TRƯỚC service (TDD). payments service chưa có nên INSERT payment trực tiếp
qua SQLAlchemy trong helper.
"""
import uuid
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient

from app.core.database import SessionFactory
from app.models.order import Order
from app.models.payment import Payment
from tests.conftest import auth_headers, login

OPEN = "/api/v1/shifts/open"
CURRENT = "/api/v1/shifts/current"
SHIFTS = "/api/v1/shifts"


def _close_url(shift_id: str) -> str:
    return f"{SHIFTS}/{shift_id}/close"


def _num(x) -> int:
    """NUMERIC có thể serialize ra số hoặc string — chuẩn hóa về int để so sánh."""
    return int(Decimal(str(x)))


# ── fixtures ────────────────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def ctx(client: AsyncClient, owner: dict) -> dict:
    """Owner + 2 branch (B1, B2) + 1 staff ở B1. Trả token/id để test."""
    owner_token = await login(client, owner["phone"], owner["password"])

    async def _branch(name: str) -> dict:
        r = await client.post("/api/v1/branches",
                              json={"name": name}, headers=auth_headers(owner_token))
        assert r.status_code == 201, r.text
        return r.json()

    branch_a = await _branch("CN A")
    branch_b = await _branch("CN B")

    r = await client.post(
        "/api/v1/users",
        json={
            "full_name": "NV A", "phone": "0900000031",
            "password": "pass123", "role": "staff", "branch_id": branch_a["id"],
        },
        headers=auth_headers(owner_token),
    )
    assert r.status_code == 201, r.text

    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_a_token": await login(client, "0900000031", "pass123"),
        "branch_a": branch_a,
        "branch_b": branch_b,
    }


async def _insert_order(ctx: dict, code: str) -> uuid.UUID:
    async with SessionFactory() as db:
        order = Order(
            tenant_id=ctx["owner"]["tenant_id"],
            branch_id=uuid.UUID(ctx["branch_a"]["id"]),
            order_code=code,
            total_amount=Decimal(0),
            created_by=ctx["owner"]["user_id"],
        )
        db.add(order)
        await db.commit()
        return order.id


async def _insert_payment(ctx: dict, shift_id, amount, method, *, order_id=None,
                          ttype="payment") -> None:
    """INSERT payment trực tiếp (payments service chưa tồn tại)."""
    async with SessionFactory() as db:
        db.add(
            Payment(
                tenant_id=ctx["owner"]["tenant_id"],
                branch_id=uuid.UUID(ctx["branch_a"]["id"]),
                order_id=order_id,
                shift_id=uuid.UUID(str(shift_id)),
                amount=Decimal(amount),
                payment_method=method,
                transaction_type=ttype,
                created_by=ctx["owner"]["user_id"],
            )
        )
        await db.commit()


async def _open(client: AsyncClient, token: str, opening_cash: int, branch_id=None) -> dict:
    body = {"opening_cash": opening_cash}
    if branch_id is not None:
        body["branch_id"] = branch_id
    return await client.post(OPEN, json=body, headers=auth_headers(token))


# ── mở ca ───────────────────────────────────────────────────────────────────
async def test_open_shift_success(client: AsyncClient, ctx: dict):
    resp = await _open(client, ctx["staff_a_token"], 500000)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "open"
    assert body["branch_id"] == ctx["branch_a"]["id"]
    assert _num(body["opening_cash"]) == 500000
    # Tên người mở nhúng sẵn trong response (staff không cần GET /users).
    assert body["opened_by_name"] == "NV A"
    assert body["closed_by_name"] is None


async def test_open_shift_already_open_409(client: AsyncClient, ctx: dict):
    await _open(client, ctx["staff_a_token"], 100000)
    resp = await _open(client, ctx["staff_a_token"], 200000)
    assert resp.status_code == 409
    assert resp.json()["code"] == "SHIFT_ALREADY_OPEN"


async def test_owner_must_pass_branch_id(client: AsyncClient, ctx: dict):
    resp = await _open(client, ctx["owner_token"], 100000)  # không branch_id
    assert resp.status_code == 400
    assert resp.json()["code"] == "BRANCH_REQUIRED"
    # Có branch_id thì OK.
    ok = await _open(client, ctx["owner_token"], 100000, branch_id=ctx["branch_a"]["id"])
    assert ok.status_code == 201


async def test_staff_cannot_open_other_branch(client: AsyncClient, ctx: dict):
    resp = await _open(client, ctx["staff_a_token"], 100000, branch_id=ctx["branch_b"]["id"])
    assert resp.status_code == 403


# ── đóng ca: reconciliation ─────────────────────────────────────────────────
async def test_close_mixed_methods(client: AsyncClient, ctx: dict):
    opened = await _open(client, ctx["staff_a_token"], 100000)
    sid = opened.json()["id"]

    order1 = await _insert_order(ctx, "B1-00001")
    order2 = await _insert_order(ctx, "B1-00002")
    # cash: +50000, +30000, refund -10000  -> cash sum = 70000
    await _insert_payment(ctx, sid, 50000, "cash", order_id=order1)
    await _insert_payment(ctx, sid, 30000, "cash", order_id=order2)
    await _insert_payment(ctx, sid, -10000, "cash", order_id=order1, ttype="refund")
    # các method khác
    await _insert_payment(ctx, sid, 200000, "transfer", order_id=order1)
    await _insert_payment(ctx, sid, 20000, "qr", order_id=order2)
    await _insert_payment(ctx, sid, 15000, "cod")  # order_id null -> không tính orders_count

    resp = await client.post(
        _close_url(sid), json={"closing_cash_actual": 175000},
        headers=auth_headers(ctx["staff_a_token"]),
    )
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert b["status"] == "closed"
    assert _num(b["closing_cash_expected"]) == 170000  # 100000 + 70000
    assert _num(b["closing_cash_actual"]) == 175000
    assert _num(b["cash_difference"]) == 5000          # 175000 - 170000
    assert _num(b["total_cash"]) == 70000
    assert _num(b["total_transfer"]) == 200000
    assert _num(b["total_qr"]) == 20000
    assert _num(b["total_cod"]) == 15000
    assert b["orders_count"] == 2                       # distinct order1, order2
    assert b["closed_at"] is not None
    assert b["opened_by_name"] == "NV A"
    assert b["closed_by_name"] == "NV A"


async def test_close_no_payments_expected_equals_opening(client: AsyncClient, ctx: dict):
    opened = await _open(client, ctx["staff_a_token"], 300000)
    sid = opened.json()["id"]
    resp = await client.post(
        _close_url(sid), json={"closing_cash_actual": 300000},
        headers=auth_headers(ctx["staff_a_token"]),
    )
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert _num(b["closing_cash_expected"]) == 300000
    assert _num(b["cash_difference"]) == 0
    assert _num(b["total_cash"]) == 0
    assert _num(b["total_transfer"]) == 0
    assert _num(b["total_qr"]) == 0
    assert _num(b["total_cod"]) == 0
    assert b["orders_count"] == 0


async def test_close_twice_409(client: AsyncClient, ctx: dict):
    opened = await _open(client, ctx["staff_a_token"], 100000)
    sid = opened.json()["id"]
    first = await client.post(
        _close_url(sid), json={"closing_cash_actual": 100000},
        headers=auth_headers(ctx["staff_a_token"]),
    )
    assert first.status_code == 200
    second = await client.post(
        _close_url(sid), json={"closing_cash_actual": 100000},
        headers=auth_headers(ctx["staff_a_token"]),
    )
    assert second.status_code == 409
    assert second.json()["code"] == "SHIFT_CLOSED"


async def test_can_reopen_branch_after_close(client: AsyncClient, ctx: dict):
    """Sau khi đóng ca, branch lại mở được ca mới (partial unique index nhả)."""
    opened = await _open(client, ctx["staff_a_token"], 100000)
    await client.post(
        _close_url(opened.json()["id"]), json={"closing_cash_actual": 100000},
        headers=auth_headers(ctx["staff_a_token"]),
    )
    again = await _open(client, ctx["staff_a_token"], 50000)
    assert again.status_code == 201


# ── GET current / list / by id ──────────────────────────────────────────────
async def test_get_current(client: AsyncClient, ctx: dict):
    opened = await _open(client, ctx["staff_a_token"], 100000)
    sid = opened.json()["id"]

    cur = await client.get(CURRENT, headers=auth_headers(ctx["staff_a_token"]))
    assert cur.status_code == 200
    assert cur.json()["id"] == sid

    # Đóng ca -> không còn ca current.
    await client.post(
        _close_url(sid), json={"closing_cash_actual": 100000},
        headers=auth_headers(ctx["staff_a_token"]),
    )
    none = await client.get(CURRENT, headers=auth_headers(ctx["staff_a_token"]))
    assert none.status_code == 404
    assert none.json()["code"] == "NO_OPEN_SHIFT"


async def test_list_and_get_by_id(client: AsyncClient, ctx: dict):
    opened = await _open(client, ctx["staff_a_token"], 100000)
    sid = opened.json()["id"]

    lst = await client.get(SHIFTS, headers=auth_headers(ctx["staff_a_token"]))
    assert lst.status_code == 200
    assert lst.json()["total"] == 1

    one = await client.get(f"{SHIFTS}/{sid}", headers=auth_headers(ctx["staff_a_token"]))
    assert one.status_code == 200
    assert one.json()["id"] == sid


async def test_owner_filter_by_branch(client: AsyncClient, ctx: dict):
    await _open(client, ctx["staff_a_token"], 100000)  # ca ở branch A
    # owner lọc theo branch B -> 0 ca.
    resp = await client.get(
        f"{SHIFTS}?branch_id={ctx['branch_b']['id']}",
        headers=auth_headers(ctx["owner_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["total"] == 0
