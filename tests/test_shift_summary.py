"""Test GET /shifts/{id}/summary — chỉ số realtime ca đang mở (Stage 6.1). TDD.

Phân biệt: total_collected (TIỀN THU, theo ca thu — gồm đơn nợ ca trước thu ca này)
vs shift_revenue (DOANH THU, theo ca TẠO đơn). Hai số lệch khi có đơn nợ qua ca —
đó là ĐÚNG kế toán.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient

from app.core.database import SessionFactory
from app.models.cash_transaction import CashTransaction
from app.models.order import Order
from app.models.payment import Payment
from tests.conftest import auth_headers, login

SHIFTS = "/api/v1/shifts"


def _num(x) -> int:
    return int(Decimal(str(x)))


@pytest_asyncio.fixture
async def sctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"}, headers=auth_headers(owner_token))
    branch = r.json()
    await client.post("/api/v1/users", json={
        "full_name": "NV A", "phone": "0900000081", "password": "pass123",
        "role": "staff", "branch_id": branch["id"]}, headers=auth_headers(owner_token))
    return {
        "owner": owner, "owner_token": owner_token,
        "staff_token": await login(client, "0900000081", "pass123"),
        "branch": branch,
    }


async def _add_order(sctx: dict, total: int, created_at: datetime) -> uuid.UUID:
    async with SessionFactory() as db:
        o = Order(
            tenant_id=sctx["owner"]["tenant_id"], branch_id=uuid.UUID(sctx["branch"]["id"]),
            order_code=f"X-{uuid.uuid4().hex[:6]}", total_amount=Decimal(total), subtotal=Decimal(total),
            pickup_at=created_at + timedelta(hours=4), created_by=sctx["owner"]["user_id"],
            created_at=created_at,
        )
        db.add(o)
        await db.commit()
        return o.id


async def _pay(sctx: dict, shift_id, order_id, amount: int, method: str) -> None:
    async with SessionFactory() as db:
        db.add(Payment(
            tenant_id=sctx["owner"]["tenant_id"], branch_id=uuid.UUID(sctx["branch"]["id"]),
            order_id=order_id, shift_id=uuid.UUID(str(shift_id)), amount=Decimal(amount),
            payment_method=method, transaction_type="payment", created_by=sctx["owner"]["user_id"],
        ))
        await db.commit()


async def _cash_txn(sctx: dict, shift_id, ttype: str, amount: int, method="cash") -> None:
    async with SessionFactory() as db:
        db.add(CashTransaction(
            tenant_id=sctx["owner"]["tenant_id"], branch_id=uuid.UUID(sctx["branch"]["id"]),
            shift_id=uuid.UUID(str(shift_id)), type=ttype, amount=Decimal(amount),
            category="khac", payment_method=method, created_by=sctx["owner"]["user_id"],
        ))
        await db.commit()


async def test_shift_summary_cross_shift_debt(client: AsyncClient, sctx: dict):
    """Ví dụ số có đơn nợ qua ca:
    - Mở ca S (đầu ca 50.000).
    - O1 (tạo CA TRƯỚC, 100.000) được thu 100.000 tiền mặt TRONG ca S → vào
      total_collected + két; KHÔNG vào doanh thu ca S.
    - O2 (tạo ca S, 200.000) thu 50.000 chuyển khoản (còn nợ).
    - O3 (tạo ca S, 80.000) thu đủ 80.000 tiền mặt.
    - Sổ quỹ: thu 30.000 cash, chi 10.000 cash.
    Kỳ vọng:
    - cash_in_drawer = 50.000 + (100.000+80.000) + 30.000 − 10.000 = 250.000
    - transfer_total = 50.000
    - total_collected = 180.000(cash) + 50.000(ck) = 230.000
    - shift_revenue = 200.000 + 80.000 = 280.000 (O1 KHÔNG tính — tạo ca trước)
    - order_count = 2 (O2, O3)
    """
    t = sctx["staff_token"]
    op = await client.post(f"{SHIFTS}/open", json={"opening_cash": 50000}, headers=auth_headers(t))
    assert op.status_code == 201, op.text
    sid = op.json()["id"]
    opened_at = datetime.fromisoformat(op.json()["opened_at"])

    o1 = await _add_order(sctx, 100000, opened_at - timedelta(hours=1))   # tạo CA TRƯỚC
    o2 = await _add_order(sctx, 200000, opened_at + timedelta(minutes=1))  # tạo ca này
    o3 = await _add_order(sctx, 80000, opened_at + timedelta(minutes=2))   # tạo ca này

    await _pay(sctx, sid, o1, 100000, "cash")     # thu nợ ca trước → ca này
    await _pay(sctx, sid, o2, 50000, "transfer")  # thu một phần
    await _pay(sctx, sid, o3, 80000, "cash")
    await _cash_txn(sctx, sid, "income", 30000)
    await _cash_txn(sctx, sid, "expense", 10000)

    r = await client.get(f"{SHIFTS}/{sid}/summary", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    s = r.json()
    assert _num(s["cash_in_drawer"]) == 250000
    assert _num(s["transfer_total"]) == 50000
    assert _num(s["total_collected"]) == 230000
    assert _num(s["shift_revenue"]) == 280000   # O1 nợ ca trước KHÔNG vào doanh thu ca này
    assert s["order_count"] == 2

    # cash_in_drawer KHỚP công thức đóng ca (đóng với đúng số → lệch 0).
    close = await client.post(f"{SHIFTS}/{sid}/close",
                              json={"closing_cash_actual": 250000}, headers=auth_headers(t))
    assert close.status_code == 200, close.text
    assert _num(close.json()["closing_cash_expected"]) == 250000
    assert _num(close.json()["cash_difference"]) == 0


async def test_shift_summary_transfer_not_in_drawer(client: AsyncClient, sctx: dict):
    """Chuyển khoản KHÔNG vào két nhưng vào total_collected."""
    t = sctx["staff_token"]
    op = await client.post(f"{SHIFTS}/open", json={"opening_cash": 0}, headers=auth_headers(t))
    sid = op.json()["id"]
    opened_at = datetime.fromisoformat(op.json()["opened_at"])
    o = await _add_order(sctx, 120000, opened_at + timedelta(minutes=1))
    await _pay(sctx, sid, o, 120000, "transfer")
    s = (await client.get(f"{SHIFTS}/{sid}/summary", headers=auth_headers(t))).json()
    assert _num(s["cash_in_drawer"]) == 0          # transfer không vào két
    assert _num(s["transfer_total"]) == 120000
    assert _num(s["total_collected"]) == 120000    # nhưng vào tổng thu
    assert _num(s["shift_revenue"]) == 120000


async def test_shift_summary_unpaid_order_revenue_not_collected(client: AsyncClient, sctx: dict):
    """Đơn tạo ca này còn nợ → vào shift_revenue, CHƯA vào total_collected."""
    t = sctx["staff_token"]
    op = await client.post(f"{SHIFTS}/open", json={"opening_cash": 0}, headers=auth_headers(t))
    sid = op.json()["id"]
    opened_at = datetime.fromisoformat(op.json()["opened_at"])
    await _add_order(sctx, 150000, opened_at + timedelta(minutes=1))  # tạo ca, KHÔNG thu
    s = (await client.get(f"{SHIFTS}/{sid}/summary", headers=auth_headers(t))).json()
    assert _num(s["shift_revenue"]) == 150000
    assert _num(s["total_collected"]) == 0
    assert _num(s["cash_in_drawer"]) == 0
    assert s["order_count"] == 1


async def test_shift_summary_owner_must_pass_branch_scope(client: AsyncClient, sctx: dict):
    """Staff branch khác KHÔNG xem được summary ca branch này (404/403 theo scope)."""
    t = sctx["staff_token"]
    op = await client.post(f"{SHIFTS}/open", json={"opening_cash": 0}, headers=auth_headers(t))
    sid = op.json()["id"]
    # owner xem được (toàn tenant).
    r = await client.get(f"{SHIFTS}/{sid}/summary", headers=auth_headers(sctx["owner_token"]))
    assert r.status_code == 200
