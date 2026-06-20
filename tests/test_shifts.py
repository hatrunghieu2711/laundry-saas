"""Test shift service: mở/đóng ca + reconciliation + sign convention.

Viết TRƯỚC service (TDD). payments service chưa có nên INSERT payment trực tiếp
qua SQLAlchemy trong helper.
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

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
            pickup_at=datetime.now(timezone.utc) + timedelta(hours=4),
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


async def _open(client: AsyncClient, token: str, opening_cash: int, branch_id=None, reason=None) -> dict:
    body = {"opening_cash": opening_cash}
    if branch_id is not None:
        body["branch_id"] = branch_id
    if reason is not None:
        body["opening_diff_reason"] = reason
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
        _close_url(sid),
        json={"closing_cash_actual": 175000, "cash_diff_reason": "Lệch test"},  # diff 5000 → cần lý do
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
    # Mở lại = KHỚP tiền để lại (100000) → không vướng đối chiếu đầu ca (6.55).
    again = await _open(client, ctx["staff_a_token"], 100000)
    assert again.status_code == 201


# ── Stage 6.55: đối chiếu tiền đầu ca với tiền để lại ca trước (lệch → bắt lý do) ──
async def _close(client: AsyncClient, token: str, sid: str, actual: int, handover: int = 0):
    return await client.post(
        _close_url(sid),
        json={"closing_cash_actual": actual, "handover_to_owner": handover},
        headers=auth_headers(token),
    )


async def test_open_matches_left_no_diff(client: AsyncClient, ctx: dict):
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]  # ca đầu (miễn)
    await _close(client, t, sid, 100000)                 # cash_left_for_next = 100000
    r = await _open(client, t, 100000)                   # == gợi ý → không cần lý do
    assert r.status_code == 201, r.text
    assert r.json()["opening_diff"] is None
    assert r.json()["opening_diff_reason"] is None


async def test_open_diff_without_reason_422(client: AsyncClient, ctx: dict):
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    await _close(client, t, sid, 100000)                 # để lại 100000
    r = await _open(client, t, 80000)                    # lệch −20000, THIẾU lý do
    assert r.status_code == 422
    assert r.json()["code"] == "OPENING_DIFF_REASON_REQUIRED"
    # ca KHÔNG mở nửa vời → mở lại khớp được
    assert (await _open(client, t, 100000)).status_code == 201


async def test_open_diff_with_reason_signed(client: AsyncClient, ctx: dict):
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    await _close(client, t, sid, 100000)                 # để lại 100000
    r = await _open(client, t, 80000, reason="Thiếu 20k, đã đếm lại")  # THIẾU
    assert r.status_code == 201, r.text
    assert _num(r.json()["opening_diff"]) == -20000      # âm = thiếu
    assert r.json()["opening_diff_reason"] == "Thiếu 20k, đã đếm lại"
    await _close(client, t, r.json()["id"], 80000)       # để lại 80000
    r2 = await _open(client, t, 120000, reason="Thừa 40k")  # THỪA
    assert r2.status_code == 201, r2.text
    assert _num(r2.json()["opening_diff"]) == 40000      # dương = thừa


async def test_first_shift_exempt_no_reason(client: AsyncClient, ctx: dict):
    t = ctx["staff_a_token"]
    r = await _open(client, t, 500000)  # branch chưa có ca đóng → ca ĐẦU, miễn đối chiếu
    assert r.status_code == 201, r.text
    assert r.json()["opening_diff"] is None


# ── Stage 6.33: lý do lệch tiền BẮT BUỘC khi cash_difference ≠ 0 (đai an toàn backend) ──
async def test_close_diff_without_reason_422(client: AsyncClient, ctx: dict):
    """Lệch tiền mà THIẾU lý do → 422 CASH_DIFF_REASON_REQUIRED; ca VẪN mở (không đóng nửa vời)."""
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]  # no payment → expected = 100000
    r = await client.post(
        _close_url(sid), json={"closing_cash_actual": 150000},  # diff +50000
        headers=auth_headers(t),
    )
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "CASH_DIFF_REASON_REQUIRED"
    g = await client.get(f"{SHIFTS}/{sid}", headers=auth_headers(t))
    assert g.json()["status"] == "open"
    # khoảng trắng cũng tính là thiếu
    r2 = await client.post(
        _close_url(sid), json={"closing_cash_actual": 150000, "cash_diff_reason": "   "},
        headers=auth_headers(t),
    )
    assert r2.status_code == 422
    assert r2.json()["code"] == "CASH_DIFF_REASON_REQUIRED"


async def test_close_diff_with_reason_saved(client: AsyncClient, ctx: dict):
    """Lệch + có lý do → đóng OK, cash_diff_reason LƯU đúng vào DB."""
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    r = await client.post(
        _close_url(sid),
        json={"closing_cash_actual": 150000, "cash_diff_reason": "Thối nhầm cho khách"},
        headers=auth_headers(t),
    )
    assert r.status_code == 200, r.text
    assert _num(r.json()["cash_difference"]) == 50000
    assert r.json()["cash_diff_reason"] == "Thối nhầm cho khách"
    async with SessionFactory() as db:
        val = await db.scalar(text("SELECT cash_diff_reason FROM shifts WHERE id=:i"), {"i": sid})
    assert val == "Thối nhầm cho khách"


async def test_close_matched_no_reason_ok(client: AsyncClient, ctx: dict):
    """Khớp két (diff=0) → KHÔNG bắt buộc lý do, đóng bình thường."""
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    r = await client.post(
        _close_url(sid), json={"closing_cash_actual": 100000},
        headers=auth_headers(t),
    )
    assert r.status_code == 200, r.text
    assert _num(r.json()["cash_difference"]) == 0
    assert r.json()["cash_diff_reason"] in (None, "")


# ── Stage 6.37: MỞ LẠI CA (reopen) — thu thêm sau khi đã đóng ───────────────
def _reopen_url(shift_id: str) -> str:
    return f"{SHIFTS}/{shift_id}/reopen"


async def test_reopen_then_collect_more_and_reclose(client: AsyncClient, ctx: dict):
    """Đóng → reopen (chốt bị xóa, payment GIỮ) → thu thêm → đóng lại: sổ cân gồm khoản mới."""
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    o1 = await _insert_order(ctx, "B1-RO1")
    await _insert_payment(ctx, sid, 50000, "cash", order_id=o1)
    r1 = await client.post(_close_url(sid), json={"closing_cash_actual": 150000}, headers=auth_headers(t))
    assert r1.status_code == 200, r1.text  # expected 150000, diff 0

    rr = await client.post(_reopen_url(sid), headers=auth_headers(t))
    assert rr.status_code == 200, rr.text
    b = rr.json()
    assert b["status"] == "open"
    assert b["closed_at"] is None and b["closing_cash_actual"] is None
    assert b["cash_difference"] is None and b["cash_diff_reason"] is None
    assert b["handover_to_owner"] is None and b["cash_left_for_next"] is None
    assert b["reopen_count"] == 1
    # Payment cũ GIỮ nguyên (sổ tiền bất biến): summary vẫn thấy 50000 đã thu.
    s = await client.get(f"{SHIFTS}/{sid}/summary", headers=auth_headers(t))
    assert _num(s.json()["total_collected"]) == 50000

    # Thu thêm 30000 rồi đóng lại.
    o2 = await _insert_order(ctx, "B1-RO2")
    await _insert_payment(ctx, sid, 30000, "cash", order_id=o2)
    r2 = await client.post(_close_url(sid), json={"closing_cash_actual": 180000}, headers=auth_headers(t))
    assert r2.status_code == 200, r2.text
    assert _num(r2.json()["total_cash"]) == 80000             # 50000 + 30000 (gồm khoản mới)
    assert _num(r2.json()["closing_cash_expected"]) == 180000  # 100000 + 80000
    assert _num(r2.json()["cash_difference"]) == 0             # sổ cân
    assert r2.json()["reopen_count"] == 1                      # giữ đếm reopen


async def test_reopen_open_shift_409(client: AsyncClient, ctx: dict):
    """Ca CHƯA đóng → không mở lại được."""
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    rr = await client.post(_reopen_url(sid), headers=auth_headers(t))
    assert rr.status_code == 409
    assert rr.json()["code"] == "SHIFT_NOT_CLOSED"


async def test_reopen_blocked_when_other_open(client: AsyncClient, ctx: dict):
    """Đã có ca mới mở trên branch → không mở lại ca cũ (one_open_shift_per_branch)."""
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    await client.post(_close_url(sid), json={"closing_cash_actual": 100000}, headers=auth_headers(t))
    await _open(client, t, 100000)  # ca mới mở
    rr = await client.post(_reopen_url(sid), headers=auth_headers(t))
    assert rr.status_code == 409
    assert rr.json()["code"] == "SHIFT_ALREADY_OPEN"


async def test_reopen_blocked_not_latest(client: AsyncClient, ctx: dict):
    """Chỉ mở lại được ca ĐÓNG GẦN NHẤT."""
    t = ctx["staff_a_token"]
    s1 = (await _open(client, t, 100000)).json()["id"]
    await client.post(_close_url(s1), json={"closing_cash_actual": 100000}, headers=auth_headers(t))
    s2 = (await _open(client, t, 100000)).json()["id"]
    await client.post(_close_url(s2), json={"closing_cash_actual": 100000}, headers=auth_headers(t))
    rr = await client.post(_reopen_url(s1), headers=auth_headers(t))  # s1 không phải đóng gần nhất
    assert rr.status_code == 409
    assert rr.json()["code"] == "CANNOT_REOPEN_NOT_LATEST"


async def test_reopen_writes_audit_log(client: AsyncClient, ctx: dict):
    """Reopen ghi audit_logs (ai/lúc nào/ca nào)."""
    t = ctx["staff_a_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    await client.post(_close_url(sid), json={"closing_cash_actual": 100000}, headers=auth_headers(t))
    await client.post(_reopen_url(sid), headers=auth_headers(t))
    async with SessionFactory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT action, user_id, entity_type FROM audit_logs "
                    "WHERE entity_id=:i AND action='shift.reopen'"
                ),
                {"i": sid},
            )
        ).first()
    assert row is not None
    assert row[0] == "shift.reopen"
    assert row[1] is not None          # ai (user) — có ghi
    assert row[2] == "shift"


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
