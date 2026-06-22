"""Stage 5.1 — tiền tố (prefix) order_code tùy biến per-branch. Viết TRƯỚC service (TDD).

Kiểm:
- Mặc định prefix = code branch (B1) khi chưa đặt.
- Sinh mã đúng format {prefix}-00001, tăng tuần tự, KHÔNG reset.
- Tự nới 6 chữ số khi vượt 99999 (set sequence sẵn gần trần).
- Đổi prefix CHỈ ảnh hưởng đơn MỚI; đơn cũ giữ nguyên mã.
- Prefix sai định dạng → 422 INVALID_PREFIX; trùng trong tenant → 422 PREFIX_TAKEN.
- Cách ly tenant: 2 tenant dùng cùng prefix không xung đột; không sửa chéo tenant.
"""
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from tests.conftest import auth_headers, login

BRANCHES = "/api/v1/branches"
ORDERS = "/api/v1/orders"


def _pickup(hours: float = 4) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


async def _create_branch(client: AsyncClient, token: str, name: str) -> dict:
    r = await client.post(BRANCHES, json={"name": name}, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _open_shift(client: AsyncClient, token: str) -> str:
    r = await client.post(
        "/api/v1/shifts/open", json={"opening_cash": 0}, headers=auth_headers(token)
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _create_order(client: AsyncClient, token: str, **extra):
    body = {
        "items": [{"service_name": "Giặt", "quantity": 1, "unit_price": 10000}],
        "pickup_at": _pickup(),
        **extra,
    }
    return await client.post(ORDERS, json=body, headers=auth_headers(token))


async def _set_prefix(client: AsyncClient, token: str, branch_id: str, prefix):
    return await client.patch(
        f"{BRANCHES}/{branch_id}",
        json={"order_prefix": prefix},
        headers=auth_headers(token),
    )


async def _setval(seq: str, value: int) -> None:
    """Đặt sequence per-branch tới giá trị gần trần để test nới chữ số."""
    async with SessionFactory() as db:
        await db.execute(text("SELECT setval(:s, :v, true)"), {"s": seq, "v": value})
        await db.commit()


@pytest_asyncio.fixture
async def ctx(client: AsyncClient, owner: dict) -> dict:
    """Owner + 1 branch (code B1) + staff ở branch đó + 1 ca đang mở."""
    owner_token = await login(client, owner["phone"], owner["password"])
    branch = await _create_branch(client, owner_token, "CN A")
    r = await client.post(
        "/api/v1/users",
        json={
            "full_name": "NV A",
            "phone": "0900000041",
            "password": "pass123",
            "role": "staff",
            "branch_id": branch["id"],
        },
        headers=auth_headers(owner_token),
    )
    assert r.status_code == 201, r.text
    staff_token = await login(client, "0900000041", "pass123")
    await _open_shift(client, staff_token)
    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_token": staff_token,
        "branch": branch,
    }


# ── mặc định + format ────────────────────────────────────────────────────────
async def test_default_prefix_equals_code(ctx: dict):
    assert ctx["branch"]["code"] == "B1"
    assert ctx["branch"]["order_prefix"] == "B1"


async def test_order_code_format_and_sequential(client: AsyncClient, ctx: dict):
    r1 = await _create_order(client, ctx["staff_token"])
    assert r1.status_code == 201, r1.text
    assert r1.json()["order_code"] == "B1-00001"
    r2 = await _create_order(client, ctx["staff_token"])
    assert r2.json()["order_code"] == "B1-00002"


# ── nới chữ số khi vượt 99999 (KHÔNG reset, KHÔNG trần) ──────────────────────
async def test_order_code_widens_past_99999(client: AsyncClient, ctx: dict):
    # Chưa có đơn nào → sequence ở mức START. Đặt sát trần 5 chữ số.
    # Tên sequence per-tenant: order_code_seq_{tenant_hex}_b1.
    seq = f"order_code_seq_{ctx['owner']['tenant_id'].hex}_b1"
    await _setval(seq, 99998)
    r1 = await _create_order(client, ctx["staff_token"])
    assert r1.json()["order_code"] == "B1-99999"  # vẫn 5 chữ số
    r2 = await _create_order(client, ctx["staff_token"])
    assert r2.json()["order_code"] == "B1-100000"  # tự nới 6 chữ số
    r3 = await _create_order(client, ctx["staff_token"])
    assert r3.json()["order_code"] == "B1-100001"


# ── đổi prefix chỉ ảnh hưởng đơn MỚI ────────────────────────────────────────
async def test_change_prefix_affects_new_orders_only(client: AsyncClient, ctx: dict):
    r1 = await _create_order(client, ctx["staff_token"])
    assert r1.json()["order_code"] == "B1-00001"
    old_id = r1.json()["id"]

    rp = await _set_prefix(client, ctx["owner_token"], ctx["branch"]["id"], "CH1")
    assert rp.status_code == 200, rp.text
    assert rp.json()["order_prefix"] == "CH1"

    # Đơn mới dùng prefix mới; SỐ tiếp tục (sequence không reset).
    r2 = await _create_order(client, ctx["staff_token"])
    assert r2.json()["order_code"] == "CH1-00002"

    # Đơn cũ giữ nguyên mã đã in.
    old = await client.get(
        f"{ORDERS}/{old_id}", headers=auth_headers(ctx["staff_token"])
    )
    assert old.json()["order_code"] == "B1-00001"


async def test_set_same_prefix_is_idempotent(client: AsyncClient, ctx: dict):
    # Đặt lại prefix bằng chính giá trị hiện tại không bị coi là trùng.
    r = await _set_prefix(client, ctx["owner_token"], ctx["branch"]["id"], "B1")
    assert r.status_code == 200, r.text
    assert r.json()["order_prefix"] == "B1"


# ── validate định dạng ──────────────────────────────────────────────────────
async def test_invalid_prefix_format_rejected(client: AsyncClient, ctx: dict):
    bid = ctx["branch"]["id"]
    for bad in ["CH 1", "CH-1", "CH#1", "Chi/1", "", "   "]:
        r = await _set_prefix(client, ctx["owner_token"], bid, bad)
        assert r.status_code == 422, (bad, r.text)
        assert r.json()["code"] == "INVALID_PREFIX", (bad, r.text)


# ── trùng prefix trong tenant → 422 ─────────────────────────────────────────
async def test_duplicate_prefix_rejected(client: AsyncClient, ctx: dict):
    branch_b = await _create_branch(client, ctx["owner_token"], "CN B")  # code B2
    assert branch_b["order_prefix"] == "B2"
    # Đổi prefix B2 -> "B1" (trùng branch A) → chặn.
    r = await _set_prefix(client, ctx["owner_token"], branch_b["id"], "B1")
    assert r.status_code == 422, r.text
    assert r.json()["code"] == "PREFIX_TAKEN"


# ── cách ly tenant ──────────────────────────────────────────────────────────
async def test_prefix_tenant_isolation(client: AsyncClient, ctx: dict, owner2: dict):
    owner2_token = await login(client, owner2["phone"], owner2["password"])
    # Tenant 2 tạo branch -> cũng code B1 / prefix B1, KHÔNG xung đột với tenant 1.
    b2 = await _create_branch(client, owner2_token, "CN T2")
    assert b2["order_prefix"] == "B1"

    # Tenant 2 đặt prefix "B1" (đã là B1) vẫn ok — uniqueness chỉ trong tenant 2.
    r_same = await _set_prefix(client, owner2_token, b2["id"], "B1")
    assert r_same.status_code == 200, r_same.text

    # Owner tenant 2 KHÔNG sửa được branch của tenant 1 (không thấy → 404).
    r = await _set_prefix(client, owner2_token, ctx["branch"]["id"], "ZZ9")
    assert r.status_code == 404, r.text
