"""Test sổ quỹ thu-chi (cash_transactions) — Stage 4.2.

Bao phủ:
- Tạo thu (income) / chi (expense) thành công, gắn ca đang mở.
- Cần ca đang mở (NO_OPEN_SHIFT), amount > 0 (INVALID_AMOUNT), category bắt buộc.
- Phân giải branch: owner phải truyền branch_id; staff không tạo branch khác.
- IMMUTABLE: trigger chặn UPDATE/DELETE ở DB level.
- Tích hợp đóng ca: expected = opening + cash payments + cash income - cash expense;
  transfer/qr KHÔNG vào két; total_income/total_expense (tiền mặt) lưu trên ca.
- Cách ly tenant.

Viết TRƯỚC service (TDD).
"""
import uuid
from decimal import Decimal

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from app.models.payment import Payment
from tests.conftest import auth_headers, login

CT = "/api/v1/cash-transactions"
SHIFTS = "/api/v1/shifts"


def _num(x) -> int:
    """NUMERIC có thể serialize ra số hoặc string ('5E+4') — chuẩn hóa về int."""
    return int(Decimal(str(x)))


@pytest_asyncio.fixture
async def cctx(client: AsyncClient, owner: dict) -> dict:
    """Owner + 2 branch (A, B) + 1 staff ở A."""
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
        json={"full_name": "NV A", "phone": "0900000071", "password": "pass123",
              "role": "staff", "branch_id": branch_a["id"]},
        headers=auth_headers(owner_token),
    )
    assert r.status_code == 201, r.text

    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_token": await login(client, "0900000071", "pass123"),
        "branch_a": branch_a,
        "branch_b": branch_b,
    }


async def _open_shift(client, token, opening=0, branch_id=None) -> str:
    body = {"opening_cash": opening}
    if branch_id is not None:
        body["branch_id"] = branch_id
    r = await client.post(f"{SHIFTS}/open", json=body, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _insert_cash_payment(cctx, shift_id, amount, method) -> None:
    """INSERT payment trực tiếp (order_id=None) để mô phỏng doanh thu ca."""
    async with SessionFactory() as db:
        db.add(
            Payment(
                tenant_id=cctx["owner"]["tenant_id"],
                branch_id=uuid.UUID(cctx["branch_a"]["id"]),
                order_id=None,
                shift_id=uuid.UUID(str(shift_id)),
                amount=Decimal(amount),
                payment_method=method,
                transaction_type="payment",
                created_by=cctx["owner"]["user_id"],
            )
        )
        await db.commit()


def _payload(type_, amount, *, category="Thu khác", note=None,
             payment_method="cash", branch_id=None) -> dict:
    body = {"type": type_, "amount": amount, "category": category,
            "payment_method": payment_method}
    if note is not None:
        body["note"] = note
    if branch_id is not None:
        body["branch_id"] = branch_id
    return body


# ── tạo thu / chi ─────────────────────────────────────────────────────────────
async def test_create_income_success(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    resp = await client.post(
        CT, json=_payload("income", 50000, category="Thu khác", note="Bán bao bì"),
        headers=auth_headers(cctx["staff_token"]),
    )
    assert resp.status_code == 201, resp.text
    b = resp.json()
    assert b["type"] == "income"
    assert _num(b["amount"]) == 50000          # luôn dương, không bị đảo dấu
    assert b["category"] == "Thu khác"
    assert b["note"] == "Bán bao bì"
    assert b["payment_method"] == "cash"
    assert b["branch_id"] == cctx["branch_a"]["id"]
    assert b["created_by_name"] == "NV A"
    assert b["shift_id"] is not None


async def test_create_expense_success(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    resp = await client.post(
        CT, json=_payload("expense", 30000, category="Mua vật tư"),
        headers=auth_headers(cctx["staff_token"]),
    )
    assert resp.status_code == 201, resp.text
    b = resp.json()
    assert b["type"] == "expense"
    assert _num(b["amount"]) == 30000          # magnitude dương; dấu do type
    assert b["category"] == "Mua vật tư"


async def test_create_default_method_cash(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    body = {"type": "income", "amount": 10000, "category": "Thu khác"}  # không method
    resp = await client.post(CT, json=body, headers=auth_headers(cctx["staff_token"]))
    assert resp.status_code == 201, resp.text
    assert resp.json()["payment_method"] == "cash"


# ── validate ──────────────────────────────────────────────────────────────────
async def test_create_requires_open_shift(client: AsyncClient, cctx: dict):
    # Chưa mở ca tại branch A.
    resp = await client.post(
        CT, json=_payload("income", 50000), headers=auth_headers(cctx["staff_token"]),
    )
    assert resp.status_code == 409
    assert resp.json()["code"] == "NO_OPEN_SHIFT"


async def test_create_invalid_amount(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    for bad in (0, -50000):
        resp = await client.post(
            CT, json=_payload("expense", bad), headers=auth_headers(cctx["staff_token"]),
        )
        assert resp.status_code == 422, resp.text
        assert resp.json()["code"] == "INVALID_AMOUNT"


async def test_create_category_required(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    resp = await client.post(
        CT, json=_payload("income", 50000, category="   "),
        headers=auth_headers(cctx["staff_token"]),
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "CATEGORY_REQUIRED"


async def test_create_invalid_type_422(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    body = {"type": "withdraw", "amount": 1000, "category": "x"}
    resp = await client.post(CT, json=body, headers=auth_headers(cctx["staff_token"]))
    assert resp.status_code == 422  # Literal schema chặn


# ── phân giải branch ──────────────────────────────────────────────────────────
async def test_owner_must_pass_branch_id(client: AsyncClient, cctx: dict):
    # Mở ca ở A (owner truyền branch) để có ca, nhưng tạo giao dịch không truyền branch.
    await _open_shift(client, cctx["owner_token"], branch_id=cctx["branch_a"]["id"])
    resp = await client.post(
        CT, json=_payload("income", 50000), headers=auth_headers(cctx["owner_token"]),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "BRANCH_REQUIRED"
    # Có branch_id thì OK.
    ok = await client.post(
        CT, json=_payload("income", 50000, branch_id=cctx["branch_a"]["id"]),
        headers=auth_headers(cctx["owner_token"]),
    )
    assert ok.status_code == 201, ok.text


async def test_staff_cannot_other_branch(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    resp = await client.post(
        CT, json=_payload("income", 50000, branch_id=cctx["branch_b"]["id"]),
        headers=auth_headers(cctx["staff_token"]),
    )
    assert resp.status_code == 403


# ── list + filter ─────────────────────────────────────────────────────────────
async def test_list_and_filter(client: AsyncClient, cctx: dict):
    sid = await _open_shift(client, cctx["staff_token"])
    await client.post(CT, json=_payload("income", 50000, category="Thu khác"),
                      headers=auth_headers(cctx["staff_token"]))
    await client.post(CT, json=_payload("expense", 20000, category="Tiền điện"),
                      headers=auth_headers(cctx["staff_token"]))
    await client.post(CT, json=_payload("expense", 10000, category="Mua vật tư"),
                      headers=auth_headers(cctx["staff_token"]))

    allp = await client.get(CT, headers=auth_headers(cctx["staff_token"]))
    assert allp.status_code == 200
    assert allp.json()["total"] == 3

    only_exp = await client.get(f"{CT}?type=expense",
                                headers=auth_headers(cctx["staff_token"]))
    assert only_exp.json()["total"] == 2

    by_shift = await client.get(f"{CT}?shift_id={sid}",
                                headers=auth_headers(cctx["staff_token"]))
    assert by_shift.json()["total"] == 3


# ── IMMUTABLE: trigger chặn UPDATE/DELETE ─────────────────────────────────────
async def test_immutable_no_update(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    resp = await client.post(CT, json=_payload("income", 50000),
                             headers=auth_headers(cctx["staff_token"]))
    ct_id = resp.json()["id"]
    with pytest.raises(Exception):  # trigger RAISE EXCEPTION
        async with SessionFactory() as db:
            await db.execute(
                text("UPDATE cash_transactions SET amount = 1 WHERE id = :i"),
                {"i": ct_id},
            )
            await db.commit()


async def test_immutable_no_delete(client: AsyncClient, cctx: dict):
    await _open_shift(client, cctx["staff_token"])
    resp = await client.post(CT, json=_payload("expense", 50000),
                             headers=auth_headers(cctx["staff_token"]))
    ct_id = resp.json()["id"]
    with pytest.raises(Exception):
        async with SessionFactory() as db:
            await db.execute(
                text("DELETE FROM cash_transactions WHERE id = :i"), {"i": ct_id}
            )
            await db.commit()
    # Vẫn còn (rollback).
    still = await client.get(f"{CT}/{ct_id}", headers=auth_headers(cctx["staff_token"]))
    assert still.status_code == 200


# ── tích hợp đóng ca ──────────────────────────────────────────────────────────
async def test_close_shift_with_income_expense(client: AsyncClient, cctx: dict):
    """expected = opening + cash payments + cash income - cash expense.
    transfer/qr thu-chi KHÔNG vào két."""
    sid = await _open_shift(client, cctx["staff_token"], opening=100000)

    # Doanh thu: tiền mặt 80.000 + chuyển khoản 200.000 (CK không vào két).
    await _insert_cash_payment(cctx, sid, 80000, "cash")
    await _insert_cash_payment(cctx, sid, 200000, "transfer")

    # Sổ quỹ: thu tiền mặt 50.000, chi tiền mặt 30.000 (vào/ra két).
    await client.post(CT, json=_payload("income", 50000, category="Thu khác"),
                      headers=auth_headers(cctx["staff_token"]))
    await client.post(CT, json=_payload("expense", 30000, category="Mua vật tư"),
                      headers=auth_headers(cctx["staff_token"]))
    # Thu/chi KHÔNG tiền mặt -> không ảnh hưởng két.
    await client.post(CT, json=_payload("income", 999000, payment_method="transfer",
                                        category="Thu CK"),
                      headers=auth_headers(cctx["staff_token"]))
    await client.post(CT, json=_payload("expense", 111000, payment_method="qr",
                                        category="Chi QR"),
                      headers=auth_headers(cctx["staff_token"]))

    # expected = 100000 + 80000(cash) + 50000(income cash) - 30000(expense cash) = 200000
    resp = await client.post(
        f"{SHIFTS}/{sid}/close", json={"closing_cash_actual": 200000},
        headers=auth_headers(cctx["staff_token"]),
    )
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert _num(b["closing_cash_expected"]) == 200000
    assert _num(b["cash_difference"]) == 0
    assert _num(b["total_cash"]) == 80000        # payments tiền mặt
    assert _num(b["total_transfer"]) == 200000
    assert _num(b["total_income"]) == 50000      # income TIỀN MẶT (vào két)
    assert _num(b["total_expense"]) == 30000     # expense TIỀN MẶT (ra két)


async def test_transfer_qr_not_in_expected(client: AsyncClient, cctx: dict):
    """Thu/chi qua chuyển khoản/QR không vào két -> expected = opening."""
    sid = await _open_shift(client, cctx["staff_token"], opening=0)
    await client.post(CT, json=_payload("income", 100000, payment_method="transfer",
                                        category="Thu CK"),
                      headers=auth_headers(cctx["staff_token"]))
    await client.post(CT, json=_payload("expense", 50000, payment_method="qr",
                                        category="Chi QR"),
                      headers=auth_headers(cctx["staff_token"]))
    resp = await client.post(
        f"{SHIFTS}/{sid}/close", json={"closing_cash_actual": 0},
        headers=auth_headers(cctx["staff_token"]),
    )
    assert resp.status_code == 200, resp.text
    b = resp.json()
    assert _num(b["closing_cash_expected"]) == 0   # không khoản nào vào két
    assert _num(b["cash_difference"]) == 0
    assert _num(b["total_income"]) == 0            # cash-only
    assert _num(b["total_expense"]) == 0


# ── cách ly tenant ────────────────────────────────────────────────────────────
async def test_tenant_isolation(client: AsyncClient, cctx: dict, owner2: dict):
    await _open_shift(client, cctx["staff_token"])
    created = await client.post(CT, json=_payload("income", 50000),
                                headers=auth_headers(cctx["staff_token"]))
    ct_id = created.json()["id"]

    other_token = await login(client, owner2["phone"], owner2["password"])
    # Owner2 list -> không thấy giao dịch của tenant 1.
    lst = await client.get(CT, headers=auth_headers(other_token))
    assert lst.status_code == 200
    assert lst.json()["total"] == 0
    # GET theo id -> 404.
    one = await client.get(f"{CT}/{ct_id}", headers=auth_headers(other_token))
    assert one.status_code == 404
