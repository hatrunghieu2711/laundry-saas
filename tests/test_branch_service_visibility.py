"""Test ẩn/hiện dịch vụ theo chi nhánh (branch_hidden_services) — TEST-FIRST.

Mặc định mọi dịch vụ hiện ở mọi CN (bảng rỗng = hành vi cũ); owner ẩn dịch vụ ở CN.
Ẩn = display-only (chỉ loại khỏi GET /services?branch_id; KHÔNG cấm tạo đơn / xóa data).
"""
import uuid

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from tests.conftest import auth_headers, login

SVC = "/api/v1/services"
BR = "/api/v1/branches"


@pytest_asyncio.fixture
async def vctx(client: AsyncClient, owner: dict) -> dict:
    """owner + 2 branch + 2 service (per_unit)."""
    tok = await login(client, owner["phone"], owner["password"])

    async def _branch(name: str) -> dict:
        r = await client.post(BR, json={"name": name}, headers=auth_headers(tok))
        assert r.status_code == 201, r.text
        return r.json()

    async def _svc(name: str) -> dict:
        r = await client.post(
            SVC,
            json={"name": name, "unit": "cai", "pricing_type": "per_unit", "unit_price": 30000},
            headers=auth_headers(tok),
        )
        assert r.status_code == 201, r.text
        return r.json()

    return {
        "owner": owner, "tok": tok,
        "a": await _branch("CN A"), "b": await _branch("CN B"),
        "s1": await _svc("Giặt thường"), "s2": await _svc("Giặt khô"),
    }


def _ids(resp) -> set[str]:
    return {s["id"] for s in resp.json()["items"]}


async def _hide(client, tok, branch_id, service_id, hidden=True):
    return await client.put(
        f"{BR}/{branch_id}/hidden-services/{service_id}",
        json={"hidden": hidden}, headers=auth_headers(tok),
    )


# ── lọc list_services ───────────────────────────────────────────────────────
async def test_list_services_no_branch_returns_all(client: AsyncClient, vctx: dict):
    """Không truyền branch_id → trả HẾT (hành vi cũ không vỡ)."""
    r = await client.get(f"{SVC}?limit=200", headers=auth_headers(vctx["tok"]))
    assert r.status_code == 200
    ids = _ids(r)
    assert vctx["s1"]["id"] in ids and vctx["s2"]["id"] in ids


async def test_hide_excludes_only_that_branch(client: AsyncClient, vctx: dict):
    a, b, s1, s2, tok = vctx["a"], vctx["b"], vctx["s1"], vctx["s2"], vctx["tok"]
    assert (await _hide(client, tok, a["id"], s1["id"], True)).status_code == 200

    # CN A: KHÔNG có s1, còn s2
    ra = await client.get(f'{SVC}?limit=200&branch_id={a["id"]}', headers=auth_headers(tok))
    assert s1["id"] not in _ids(ra) and s2["id"] in _ids(ra)
    # CN B: vẫn có s1 (ẩn chỉ ở A)
    rb = await client.get(f'{SVC}?limit=200&branch_id={b["id"]}', headers=auth_headers(tok))
    assert s1["id"] in _ids(rb)
    # không branch: thấy hết
    rall = await client.get(f"{SVC}?limit=200", headers=auth_headers(tok))
    assert s1["id"] in _ids(rall)


async def test_show_again_unhides(client: AsyncClient, vctx: dict):
    a, s1, tok = vctx["a"], vctx["s1"], vctx["tok"]
    await _hide(client, tok, a["id"], s1["id"], True)
    assert (await _hide(client, tok, a["id"], s1["id"], False)).status_code == 200
    ra = await client.get(f'{SVC}?limit=200&branch_id={a["id"]}', headers=auth_headers(tok))
    assert s1["id"] in _ids(ra)


async def test_hide_idempotent(client: AsyncClient, vctx: dict):
    a, s1, tok = vctx["a"], vctx["s1"], vctx["tok"]
    assert (await _hide(client, tok, a["id"], s1["id"], True)).status_code == 200
    assert (await _hide(client, tok, a["id"], s1["id"], True)).status_code == 200  # lặp → OK
    r = await client.get(f'{BR}/{a["id"]}/hidden-services', headers=auth_headers(tok))
    assert r.json()["hidden_service_ids"].count(s1["id"]) == 1


async def test_get_hidden_list(client: AsyncClient, vctx: dict):
    a, s1, tok = vctx["a"], vctx["s1"], vctx["tok"]
    await _hide(client, tok, a["id"], s1["id"], True)
    r = await client.get(f'{BR}/{a["id"]}/hidden-services', headers=auth_headers(tok))
    assert r.status_code == 200
    assert s1["id"] in r.json()["hidden_service_ids"]


# ── quyền owner-only ────────────────────────────────────────────────────────
async def test_management_owner_only(client: AsyncClient, vctx: dict):
    a, s1, tok = vctx["a"], vctx["s1"], vctx["tok"]
    # tạo staff trong cùng tenant
    r = await client.post(
        "/api/v1/users",
        json={"full_name": "NV", "phone": "0900000077", "password": "pass123",
              "role": "staff", "branch_id": a["id"]},
        headers=auth_headers(tok),
    )
    assert r.status_code == 201, r.text
    staff_tok = await login(client, "0900000077", "pass123")
    # staff PUT ẩn → 403
    assert (await _hide(client, staff_tok, a["id"], s1["id"], True)).status_code == 403
    # staff GET hidden → 403
    rg = await client.get(f'{BR}/{a["id"]}/hidden-services', headers=auth_headers(staff_tok))
    assert rg.status_code == 403


# ── RLS isolation bảng mới (⭐ BẮT BUỘC) ─────────────────────────────────────
async def _seed_hidden(tenant_id, code):
    """Seed branch + service + 1 hidden row (owner bypass RLS)."""
    async with SessionFactory() as s:
        bid = await s.scalar(
            text("INSERT INTO branches (id, tenant_id, name, code, order_prefix, status) "
                 "VALUES (gen_random_uuid(), :t, 'CN', :c, :c, 'active') RETURNING id"),
            {"t": str(tenant_id), "c": code})
        sid = await s.scalar(
            text("INSERT INTO services (id, tenant_id, name, unit, pricing_type) "
                 "VALUES (gen_random_uuid(), :t, 'Svc', 'cai', 'per_unit') RETURNING id"),
            {"t": str(tenant_id)})
        await s.execute(
            text("INSERT INTO branch_hidden_services (id, tenant_id, branch_id, service_id) "
                 "VALUES (gen_random_uuid(), :t, :b, :s)"),
            {"t": str(tenant_id), "b": str(bid), "s": str(sid)})
        await s.commit()


async def test_rls_isolation_hidden_rows(app_role_engine, owner: dict, owner2: dict):
    """Tenant A chỉ thấy hidden row của A; KHÔNG thấy của B (qua role app non-bypass)."""
    await _seed_hidden(owner["tenant_id"], "AA")
    await _seed_hidden(owner2["tenant_id"], "BB")
    async with app_role_engine.connect() as conn:
        await conn.execute(
            text("SELECT set_config('app.current_tenant_id', :t, false)"),
            {"t": str(owner["tenant_id"])})
        n_a = await conn.scalar(text("SELECT count(*) FROM branch_hidden_services"))
        assert n_a == 1, f"RLS leak: tenant A thấy {n_a} dòng (phải 1)"

        await conn.execute(
            text("SELECT set_config('app.current_tenant_id', :t, false)"),
            {"t": str(owner2["tenant_id"])})
        n_b = await conn.scalar(text("SELECT count(*) FROM branch_hidden_services"))
        assert n_b == 1, f"RLS leak: tenant B thấy {n_b} dòng (phải 1)"

        # GUC rỗng → thấy 0 (không lỗi cast)
        await conn.execute(text("SELECT set_config('app.current_tenant_id', '', false)"))
        n0 = await conn.scalar(text("SELECT count(*) FROM branch_hidden_services"))
        assert n0 == 0


# ── đơn cũ KHÔNG ảnh hưởng (snapshot) ───────────────────────────────────────
async def test_old_order_items_unchanged_after_hide(client: AsyncClient, vctx: dict, owner: dict):
    """Ẩn dịch vụ KHÔNG đụng order_items đã tạo (snapshot service_name/price)."""
    a, s1, tok = vctx["a"], vctx["s1"], vctx["tok"]
    # seed 1 đơn + item tham chiếu s1 (owner bypass)
    async with SessionFactory() as s:
        oid = await s.scalar(
            text("INSERT INTO orders (id, tenant_id, branch_id, order_code, pickup_at, created_by) "
                 "VALUES (gen_random_uuid(), :t, :b, 'AA-0001', now(), :u) RETURNING id"),
            {"t": str(owner["tenant_id"]), "b": a["id"], "u": str(owner["user_id"])})
        await s.execute(
            text("INSERT INTO order_items (id, order_id, service_id, service_name, quantity, unit_price, subtotal) "
                 "VALUES (gen_random_uuid(), :o, :sid, 'Giặt thường', 1, 30000, 30000)"),
            {"o": str(oid), "sid": s1["id"]})
        await s.commit()
    # ẩn s1 ở CN A
    await _hide(client, tok, a["id"], s1["id"], True)
    # order_items vẫn nguyên (service vẫn tồn tại, snapshot giữ)
    async with SessionFactory() as s:
        nm = await s.scalar(text("SELECT service_name FROM order_items WHERE order_id = :o"), {"o": str(oid)})
        assert nm == "Giặt thường"
        svc_active = await s.scalar(text("SELECT is_active FROM services WHERE id = :s"), {"s": s1["id"]})
        assert svc_active is True  # ẩn ≠ xóa dịch vụ
