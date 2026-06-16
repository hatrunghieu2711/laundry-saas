"""Test GET /reports/owner-summary — báo cáo cho chủ (Stage 6.3). Viết TRƯỚC (TDD).

4 nhóm: doanh thu (theo ngày/chi nhánh), nộp chủ, lệch két, nợ chưa thu. Tất cả
tenant-scoped + lọc chi nhánh + khoảng ngày (UTC, MVP).
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient

from app.core.database import SessionFactory
from app.models.order import Order
from app.models.payment import Payment
from app.models.shift import Shift
from tests.conftest import auth_headers, login

URL = "/api/v1/reports/owner-summary"


def _num(x) -> int:
    return int(Decimal(str(x)))


def _dt(s: str) -> datetime:
    return datetime.fromisoformat(s).replace(tzinfo=timezone.utc)


@pytest_asyncio.fixture
async def rctx(client: AsyncClient, owner: dict) -> dict:
    ot = await login(client, owner["phone"], owner["password"])

    async def _branch(name):
        return (await client.post("/api/v1/branches", json={"name": name}, headers=auth_headers(ot))).json()

    a = await _branch("CN A")
    b = await _branch("CN B")
    staff = (await client.post("/api/v1/users", json={
        "full_name": "NV A", "phone": "0900000101", "password": "pass123",
        "role": "staff", "branch_id": a["id"]}, headers=auth_headers(ot))).json()
    # 1 ca đang mở để payment có shift_id (NOT NULL) — không ảnh hưởng báo cáo (ca CHƯA đóng).
    async with SessionFactory() as db:
        sh = Shift(
            tenant_id=owner["tenant_id"], branch_id=uuid.UUID(a["id"]),
            opened_by=owner["user_id"], opening_cash=Decimal(0), status="open",
            opened_at=datetime(2026, 6, 9, 1, 0, tzinfo=timezone.utc),
        )
        db.add(sh)
        await db.commit()
        pay_shift_id = sh.id
    return {"owner": owner, "owner_token": ot, "a": a, "b": b,
            "staff_id": staff["id"], "pay_shift_id": pay_shift_id}


async def _order(rctx, branch, total, created_at, *, status="created", payment_status="paid"):
    async with SessionFactory() as db:
        o = Order(
            tenant_id=rctx["owner"]["tenant_id"], branch_id=uuid.UUID(branch["id"]),
            order_code=f"R-{uuid.uuid4().hex[:7]}", total_amount=Decimal(total), subtotal=Decimal(total),
            order_status=status, payment_status=payment_status,
            pickup_at=created_at + timedelta(hours=4), created_by=rctx["owner"]["user_id"], created_at=created_at,
        )
        db.add(o)
        await db.commit()
        return o.id


async def _pay(rctx, branch, order_id, amount):
    async with SessionFactory() as db:
        db.add(Payment(
            tenant_id=rctx["owner"]["tenant_id"], branch_id=uuid.UUID(branch["id"]),
            order_id=order_id, shift_id=rctx["pay_shift_id"], amount=Decimal(amount),
            payment_method="cash", transaction_type="payment", created_by=rctx["owner"]["user_id"],
        ))
        await db.commit()


async def _closed_shift(rctx, branch, *, diff, handover, closed_at, closed_by=None):
    async with SessionFactory() as db:
        db.add(Shift(
            tenant_id=rctx["owner"]["tenant_id"], branch_id=uuid.UUID(branch["id"]),
            opened_by=rctx["owner"]["user_id"], closed_by=closed_by or rctx["owner"]["user_id"],
            opening_cash=Decimal(0), closing_cash_expected=Decimal(0),
            closing_cash_actual=Decimal(diff), cash_difference=Decimal(diff),
            handover_to_owner=Decimal(handover), cash_left_for_next=Decimal(0),
            status="closed", opened_at=closed_at - timedelta(hours=8), closed_at=closed_at,
        ))
        await db.commit()


@pytest_asyncio.fixture
async def seeded(rctx: dict):
    """Dữ liệu trong khoảng 2026-06-10 .. 2026-06-12 (+ vài cái ngoài khoảng)."""
    a, b = rctx["a"], rctx["b"]
    # Doanh thu + nợ
    await _order(rctx, a, 100000, _dt("2026-06-10T03:00:00"))                                   # paid
    o2 = await _order(rctx, a, 200000, _dt("2026-06-11T03:00:00"), payment_status="partial")     # nợ 150k
    await _pay(rctx, a, o2, 50000)
    await _order(rctx, b, 80000, _dt("2026-06-11T03:00:00"), payment_status="unpaid")            # nợ 80k (CN B)
    await _order(rctx, a, 999000, _dt("2026-06-20T03:00:00"))                                    # NGOÀI khoảng
    await _order(rctx, a, 50000, _dt("2026-06-10T03:00:00"), status="cancelled", payment_status="unpaid")  # hủy → bỏ
    # Ca đóng
    await _closed_shift(rctx, a, diff=-20000, handover=300000, closed_at=_dt("2026-06-10T10:00:00"), closed_by=rctx["staff_id"])
    await _closed_shift(rctx, a, diff=0, handover=0, closed_at=_dt("2026-06-11T10:00:00"))         # khớp
    await _closed_shift(rctx, b, diff=5000, handover=100000, closed_at=_dt("2026-06-11T11:00:00"))
    await _closed_shift(rctx, a, diff=-99999, handover=500000, closed_at=_dt("2026-06-25T10:00:00"))  # NGOÀI khoảng
    return rctx


def _q(frm="2026-06-10", to="2026-06-12", branch=None):
    s = f"?from_date={frm}&to_date={to}"
    return s + (f"&branch_id={branch}" if branch else "")


async def test_summary_all_branches(client: AsyncClient, seeded: dict):
    t = seeded["owner_token"]
    r = await client.get(f"{URL}{_q()}", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    s = r.json()
    # a) DOANH THU = 100k + 200k + 80k = 380k (đơn ngoài khoảng + hủy bị loại).
    assert _num(s["revenue"]["total"]) == 380000
    by_day = {d["date"]: _num(d["revenue"]) for d in s["revenue"]["by_day"]}
    assert by_day["2026-06-10"] == 100000
    assert by_day["2026-06-11"] == 280000  # 200k(A) + 80k(B)
    by_branch = {x["branch_id"]: _num(x["revenue"]) for x in s["revenue"]["by_branch"]}
    assert by_branch[seeded["a"]["id"]] == 300000 and by_branch[seeded["b"]["id"]] == 80000
    # b) NỘP CHỦ = 300k + 100k (ca khớp handover 0 không tính) = 400k, 2 khoản.
    assert _num(s["handover"]["total"]) == 400000 and s["handover"]["count"] == 2
    # c) LỆCH KÉT: 2 ca lệch (-20k, +5k) → net -15k; 1 ca khớp.
    assert s["cash_diff"]["count"] == 2 and s["cash_diff"]["matched_count"] == 1
    assert _num(s["cash_diff"]["total"]) == -15000
    diffs = sorted(_num(x["cash_difference"]) for x in s["cash_diff"]["rows"])
    assert diffs == [-20000, 5000]
    assert all(_num(x["cash_difference"]) != 0 for x in s["cash_diff"]["rows"])
    # d) NỢ CHƯA THU = 150k (O2 partial) + 80k (O3 unpaid) = 230k, 2 đơn.
    assert _num(s["unpaid"]["total_outstanding"]) == 230000 and s["unpaid"]["order_count"] == 2


async def test_summary_branch_filter(client: AsyncClient, seeded: dict):
    t = seeded["owner_token"]
    s = (await client.get(f"{URL}{_q(branch=seeded['a']['id'])}", headers=auth_headers(t))).json()
    assert _num(s["revenue"]["total"]) == 300000          # chỉ CN A
    assert _num(s["handover"]["total"]) == 300000          # ca A rút 300k
    assert s["cash_diff"]["count"] == 1                    # chỉ ca A lệch (-20k)
    assert _num(s["cash_diff"]["total"]) == -20000
    assert _num(s["unpaid"]["total_outstanding"]) == 150000 and s["unpaid"]["order_count"] == 1


async def test_summary_cash_diff_all_matched_lists_none(client: AsyncClient, rctx: dict):
    t = rctx["owner_token"]
    await _closed_shift(rctx, rctx["a"], diff=0, handover=0, closed_at=_dt("2026-06-10T10:00:00"))
    s = (await client.get(f"{URL}{_q()}", headers=auth_headers(t))).json()
    assert s["cash_diff"]["count"] == 0 and s["cash_diff"]["rows"] == []
    assert s["cash_diff"]["matched_count"] == 1


async def test_summary_empty_range(client: AsyncClient, seeded: dict):
    """Khoảng rỗng (tương lai) → tất cả 0."""
    t = seeded["owner_token"]
    s = (await client.get(f"{URL}{_q('2027-01-01', '2027-01-02')}", headers=auth_headers(t))).json()
    assert _num(s["revenue"]["total"]) == 0 and s["revenue"]["by_day"] == []
    assert _num(s["handover"]["total"]) == 0
    assert s["cash_diff"]["count"] == 0
    assert _num(s["unpaid"]["total_outstanding"]) == 0


async def test_summary_single_day(client: AsyncClient, seeded: dict):
    """from=to=2026-06-10 (biên) → chỉ ngày đó."""
    t = seeded["owner_token"]
    s = (await client.get(f"{URL}{_q('2026-06-10', '2026-06-10')}", headers=auth_headers(t))).json()
    assert _num(s["revenue"]["total"]) == 100000
    assert _num(s["handover"]["total"]) == 300000   # ca đóng 06-10
    assert s["cash_diff"]["count"] == 1


async def test_summary_owner_only(client: AsyncClient, rctx: dict):
    staff = await login(client, "0900000101", "pass123")
    bad = await client.get(f"{URL}{_q()}", headers=auth_headers(staff))
    assert bad.status_code == 403


async def test_summary_tenant_isolation(client: AsyncClient, seeded: dict, owner2: dict):
    t2 = await login(client, owner2["phone"], owner2["password"])
    s = (await client.get(f"{URL}{_q()}", headers=auth_headers(t2))).json()
    assert _num(s["revenue"]["total"]) == 0          # tenant 2 không thấy dữ liệu tenant 1
    assert _num(s["handover"]["total"]) == 0
    assert _num(s["unpaid"]["total_outstanding"]) == 0
