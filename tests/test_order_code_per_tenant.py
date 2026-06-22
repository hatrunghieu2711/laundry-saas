"""Bug fix: sequence order_code PER-TENANT (không dùng chung giữa tenant).

⚠️ VÙNG TÀI CHÍNH: mỗi tenant đếm độc lập từ 1; KHÔNG reset số tenant đang chạy
(uq_orders_tenant_order_code chặn trùng). Tên sequence kèm tenant_id:
  order_code_seq_{tenant_id_hex}_{code}.
"""
import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from tests.conftest import auth_headers, login

BRANCHES = "/api/v1/branches"
ORDERS = "/api/v1/orders"


def _seq_name(tenant_id, code: str = "b1") -> str:
    return f"order_code_seq_{uuid.UUID(str(tenant_id)).hex}_{code.lower()}"


def _pickup(h: float = 4) -> str:
    return (datetime.now(timezone.utc) + timedelta(hours=h)).isoformat()


async def _make_branch(client: AsyncClient, token: str, name: str) -> dict:
    r = await client.post(BRANCHES, json={"name": name}, headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()


async def _order(client: AsyncClient, token: str, branch_id: str):
    body = {
        "items": [{"service_name": "Giặt", "quantity": 1, "unit_price": 10000}],
        "pickup_at": _pickup(),
        "branch_id": branch_id,
    }
    return await client.post(ORDERS, json=body, headers=auth_headers(token))


# ── ⭐ KHÔNG reset: sequence tiếp tục (mô phỏng 2H B1=69 → đơn kế 70) ─────────
async def test_sequence_continues_no_reset(client: AsyncClient, owner: dict):
    token = await login(client, owner["phone"], owner["password"])
    branch = await _make_branch(client, token, "CN A")

    # Đẩy sequence của B1 tới 69 (như 2H sau rename) → đơn kế tiếp = 70, KHÔNG reset.
    async with SessionFactory() as db:
        await db.execute(
            text("SELECT setval(:s, 69, true)"), {"s": _seq_name(owner["tenant_id"])}
        )
        await db.commit()

    r = await _order(client, token, branch["id"])
    assert r.status_code == 201, r.text
    assert r.json()["order_code"] == "B1-00070"


# ── ⭐ HAI TENANT độc lập: mỗi CN B1 → sequence RIÊNG → đơn đầu mỗi tenant 00001 ──
async def test_two_tenants_independent_sequences(
    client: AsyncClient, owner: dict, owner2: dict
):
    t1 = await login(client, owner["phone"], owner["password"])
    b1 = await _make_branch(client, t1, "CN1")
    t2 = await login(client, owner2["phone"], owner2["password"])
    b2 = await _make_branch(client, t2, "CN2")

    # Cả hai CN đầu đều code B1 — TRƯỚC fix sẽ dùng CHUNG order_code_seq_b1.
    assert b1["code"] == "B1" and b2["code"] == "B1"
    assert _seq_name(owner["tenant_id"]) != _seq_name(owner2["tenant_id"])

    # tenant1 tạo 3 đơn → 00001..00003.
    for n in (1, 2, 3):
        r = await _order(client, t1, b1["id"])
        assert r.status_code == 201, r.text
        assert r.json()["order_code"] == f"B1-{n:05d}"

    # tenant2 đơn ĐẦU → VẪN 00001 (KHÔNG nhảy theo tenant1). ← bug gốc đã tách.
    r = await _order(client, t2, b2["id"])
    assert r.status_code == 201, r.text
    assert r.json()["order_code"] == "B1-00001"

    # 2 sequence riêng tồn tại trong DB.
    async with SessionFactory() as db:
        for tid in (owner["tenant_id"], owner2["tenant_id"]):
            assert await db.scalar(
                text("SELECT 1 FROM pg_class WHERE relkind='S' AND relname=:n"),
                {"n": _seq_name(tid)},
            ) == 1


# ── tên sequence tạo theo branch đúng format mới (kèm tenant_id) ─────────────
async def test_created_sequence_uses_new_name(client: AsyncClient, owner: dict):
    token = await login(client, owner["phone"], owner["password"])
    await _make_branch(client, token, "CN A")
    async with SessionFactory() as db:
        # tên CŨ (không tenant) KHÔNG còn được tạo.
        assert await db.scalar(
            text("SELECT 1 FROM pg_class WHERE relkind='S' AND relname='order_code_seq_b1'")
        ) is None
        # tên MỚI (kèm tenant_id) tồn tại.
        assert await db.scalar(
            text("SELECT 1 FROM pg_class WHERE relkind='S' AND relname=:n"),
            {"n": _seq_name(owner["tenant_id"])},
        ) == 1


# ── regex function mới: chấp nhận tên mới hợp lệ; reject tên cũ/xấu (injection) ──
async def test_function_accepts_new_name(owner: dict):
    name = _seq_name(owner["tenant_id"])
    async with SessionFactory() as s:
        await s.execute(text("SELECT app_create_order_seq(:n)"), {"n": name})
        await s.commit()
        assert await s.scalar(text(f"SELECT nextval('{name}')")) == 1


async def test_function_rejects_old_name():
    """Tên CŨ (order_code_seq_b1, thiếu tenant_id) → regex mới CHẶN."""
    async with SessionFactory() as s:
        with pytest.raises(Exception):
            await s.execute(
                text("SELECT app_create_order_seq(:n)"), {"n": "order_code_seq_b1"}
            )


async def test_function_rejects_injection():
    async with SessionFactory() as s:
        with pytest.raises(Exception):
            await s.execute(
                text("SELECT app_create_order_seq(:n)"), {"n": "evil; DROP TABLE x"}
            )
