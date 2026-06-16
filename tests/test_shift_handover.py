"""Test đóng ca: rút tiền nộp chủ + gợi ý mở ca + báo cáo nộp chủ (Stage 6.2). TDD.

handover_to_owner là tiền RA khỏi két SAU đối soát (không phải chi phí, không vào
expected). cash_left_for_next = closing_cash_actual − handover_to_owner → gợi ý
đầu ca sau (nhân viên đếm lại).
"""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient

from app.core.database import SessionFactory
from app.models.payment import Payment
from tests.conftest import auth_headers, login

SHIFTS = "/api/v1/shifts"
HANDOVER_REPORT = "/api/v1/reports/owner-handover"


def _num(x) -> int:
    return int(Decimal(str(x)))


@pytest_asyncio.fixture
async def hctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"}, headers=auth_headers(owner_token))
    branch = r.json()
    await client.post("/api/v1/users", json={
        "full_name": "NV A", "phone": "0900000091", "password": "pass123",
        "role": "staff", "branch_id": branch["id"]}, headers=auth_headers(owner_token))
    return {
        "owner": owner, "owner_token": owner_token,
        "staff_token": await login(client, "0900000091", "pass123"),
        "branch": branch,
    }


async def _pay_cash(hctx: dict, shift_id, amount: int) -> None:
    async with SessionFactory() as db:
        db.add(Payment(
            tenant_id=hctx["owner"]["tenant_id"], branch_id=uuid.UUID(hctx["branch"]["id"]),
            order_id=None, shift_id=uuid.UUID(str(shift_id)), amount=Decimal(amount),
            payment_method="cash", transaction_type="payment", created_by=hctx["owner"]["user_id"],
        ))
        await db.commit()


async def _open(client, token, opening):
    return await client.post(f"{SHIFTS}/open", json={"opening_cash": opening}, headers=auth_headers(token))


async def test_close_with_handover_sets_cash_left(client: AsyncClient, hctx: dict):
    """Ví dụ: đầu ca 100.000 + thu cash 300.000 → expected 400.000. Đếm thực tế
    400.000, rút nộp chủ 250.000 → để lại ca sau 150.000. Expected KHÔNG đổi."""
    t = hctx["staff_token"]
    sid = (await _open(client, t, 100000)).json()["id"]
    await _pay_cash(hctx, sid, 300000)
    r = await client.post(f"{SHIFTS}/{sid}/close", json={
        "closing_cash_actual": 400000, "handover_to_owner": 250000}, headers=auth_headers(t))
    assert r.status_code == 200, r.text
    b = r.json()
    assert _num(b["closing_cash_expected"]) == 400000   # đầu ca + cash thu (handover KHÔNG ảnh hưởng)
    assert _num(b["cash_difference"]) == 0
    assert _num(b["handover_to_owner"]) == 250000
    assert _num(b["cash_left_for_next"]) == 150000      # 400.000 − 250.000


async def test_close_handover_zero_keeps_all(client: AsyncClient, hctx: dict):
    t = hctx["staff_token"]
    sid = (await _open(client, t, 50000)).json()["id"]
    await _pay_cash(hctx, sid, 20000)
    r = await client.post(f"{SHIFTS}/{sid}/close", json={"closing_cash_actual": 70000}, headers=auth_headers(t))
    assert r.status_code == 200, r.text
    b = r.json()
    assert _num(b["handover_to_owner"]) == 0
    assert _num(b["cash_left_for_next"]) == 70000       # để lại toàn bộ


async def test_close_handover_exceeds_actual_422(client: AsyncClient, hctx: dict):
    t = hctx["staff_token"]
    sid = (await _open(client, t, 0)).json()["id"]
    await _pay_cash(hctx, sid, 100000)
    r = await client.post(f"{SHIFTS}/{sid}/close", json={
        "closing_cash_actual": 100000, "handover_to_owner": 150000}, headers=auth_headers(t))
    assert r.status_code == 422
    assert r.json()["code"] == "HANDOVER_EXCEEDS_CASH"


async def test_opening_suggestion_from_last_cash_left(client: AsyncClient, hctx: dict):
    """Mở ca sau gợi ý = cash_left_for_next ca đóng gần nhất cùng branch."""
    t = hctx["staff_token"]
    # chưa có ca đóng → gợi ý 0.
    sug0 = await client.get(f"{SHIFTS}/opening-suggestion", headers=auth_headers(t))
    assert sug0.status_code == 200 and _num(sug0.json()["suggested_opening_cash"]) == 0
    # đóng 1 ca để lại 150.000.
    sid = (await _open(client, t, 100000)).json()["id"]
    await _pay_cash(hctx, sid, 300000)
    await client.post(f"{SHIFTS}/{sid}/close", json={
        "closing_cash_actual": 400000, "handover_to_owner": 250000}, headers=auth_headers(t))
    sug = await client.get(f"{SHIFTS}/opening-suggestion", headers=auth_headers(t))
    assert _num(sug.json()["suggested_opening_cash"]) == 150000  # = cash_left ca trước


async def test_owner_handover_report_lists_and_totals(client: AsyncClient, hctx: dict):
    t = hctx["staff_token"]
    # ca 1: rút 250.000.
    s1 = (await _open(client, t, 100000)).json()["id"]
    await _pay_cash(hctx, s1, 300000)
    await client.post(f"{SHIFTS}/{s1}/close", json={
        "closing_cash_actual": 400000, "handover_to_owner": 250000}, headers=auth_headers(t))
    # ca 2: rút 0 → KHÔNG vào báo cáo.
    s2 = (await _open(client, t, 150000)).json()["id"]
    await client.post(f"{SHIFTS}/{s2}/close", json={"closing_cash_actual": 150000}, headers=auth_headers(t))
    # ca 3: rút 80.000.
    s3 = (await _open(client, t, 150000)).json()["id"]
    await _pay_cash(hctx, s3, 50000)
    await client.post(f"{SHIFTS}/{s3}/close", json={
        "closing_cash_actual": 200000, "handover_to_owner": 80000}, headers=auth_headers(t))

    r = await client.get(HANDOVER_REPORT, headers=auth_headers(hctx["owner_token"]))
    assert r.status_code == 200, r.text
    data = r.json()
    assert _num(data["total"]) == 330000   # 250.000 + 80.000 (ca rút 0 không tính)
    assert data["count"] == 2
    amounts = sorted(_num(x["amount"]) for x in data["rows"])
    assert amounts == [80000, 250000]
    # mỗi dòng có thông tin ca + nhân viên + giờ.
    row = data["rows"][0]
    for k in ("shift_id", "opened_at", "closed_at", "staff_name", "amount"):
        assert k in row


async def test_owner_handover_report_owner_only(client: AsyncClient, hctx: dict):
    bad = await client.get(HANDOVER_REPORT, headers=auth_headers(hctx["staff_token"]))
    assert bad.status_code == 403
