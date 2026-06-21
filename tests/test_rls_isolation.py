"""Test RLS CÁCH LY THẬT (R3) — connect bằng `laundry_app` (non-bypass).

Nghiệm thu: tenant A KHÔNG đọc/ghi được data tenant B — KỂ CẢ khi cố tình bỏ filter
tay (query trần `SELECT * FROM customers`). Seed bằng OWNER (SessionFactory, bypass
RLS); kiểm bằng `app_role_engine` (role app, RLS có hiệu lực).

Skip nếu môi trường không có DSN role-app (xem fixture app_role_engine).
"""
import uuid

import pytest
from sqlalchemy import text

from app.core.database import SessionFactory
from app.models.customer import Customer

_SET_TENANT = "SELECT set_config('app.current_tenant_id', :t, false)"


async def _seed_customer(tenant_id: uuid.UUID, name: str) -> uuid.UUID:
    """Seed bằng owner (bypass RLS) — không phụ thuộc GUC."""
    async with SessionFactory() as s:
        c = Customer(tenant_id=tenant_id, full_name=name)
        s.add(c)
        await s.commit()
        return c.id


async def test_rls_read_isolation(app_role_engine, owner, owner2):
    """Context = tenant A → query TRẦN chỉ thấy customer của A, KHÔNG thấy của B."""
    await _seed_customer(owner["tenant_id"], "Khach A")
    await _seed_customer(owner2["tenant_id"], "Khach B")

    async with app_role_engine.connect() as conn:
        await conn.execute(text(_SET_TENANT), {"t": str(owner["tenant_id"])})
        names = (await conn.execute(text("SELECT full_name FROM customers"))).scalars().all()
        assert names == ["Khach A"], f"RLS read leak: {names!r}"

        # đổi context sang B → chỉ thấy B
        await conn.execute(text(_SET_TENANT), {"t": str(owner2["tenant_id"])})
        names_b = (await conn.execute(text("SELECT full_name FROM customers"))).scalars().all()
        assert names_b == ["Khach B"], f"RLS read leak: {names_b!r}"


async def test_rls_write_check_blocks_cross_tenant(app_role_engine, owner, owner2):
    """Context = A → INSERT customer cho tenant B bị WITH CHECK chặn."""
    async with app_role_engine.connect() as conn:
        await conn.execute(text(_SET_TENANT), {"t": str(owner["tenant_id"])})
        with pytest.raises(Exception):  # new row violates row-level security policy
            await conn.execute(
                text(
                    "INSERT INTO customers (id, tenant_id, full_name) "
                    "VALUES (gen_random_uuid(), :b, 'evil cross-tenant')"
                ),
                {"b": str(owner2["tenant_id"])},
            )
        await conn.rollback()


async def test_rls_update_cannot_move_row_to_other_tenant(app_role_engine, owner, owner2):
    """Context = A → UPDATE customer của A sang tenant_id B bị WITH CHECK chặn."""
    cid = await _seed_customer(owner["tenant_id"], "Khach A")
    async with app_role_engine.connect() as conn:
        await conn.execute(text(_SET_TENANT), {"t": str(owner["tenant_id"])})
        with pytest.raises(Exception):
            await conn.execute(
                text("UPDATE customers SET tenant_id = :b WHERE id = :id"),
                {"b": str(owner2["tenant_id"]), "id": str(cid)},
            )
        await conn.rollback()


async def test_rls_empty_context_sees_nothing(app_role_engine, owner):
    """GUC rỗng → không match → thấy RỖNG (không lỗi cast)."""
    await _seed_customer(owner["tenant_id"], "Khach A")
    async with app_role_engine.connect() as conn:
        await conn.execute(text("SELECT set_config('app.current_tenant_id', '', false)"))
        n = await conn.scalar(text("SELECT count(*) FROM customers"))
        assert n == 0


async def _seed_order_item(tenant_id, user_id, code, item_name):
    """Seed branch + order + order_item tối thiểu (raw SQL, owner bypass RLS).

    orders có nhiều cột NOT NULL (branch_id, created_by, pickup_at, order_code);
    các cột tiền/trạng thái dùng server_default."""
    async with SessionFactory() as s:
        bid = await s.scalar(
            text(
                "INSERT INTO branches (id, tenant_id, name, code, order_prefix, status) "
                "VALUES (gen_random_uuid(), :t, 'CN', :c, :c, 'active') RETURNING id"
            ),
            {"t": str(tenant_id), "c": code},
        )
        oid = await s.scalar(
            text(
                "INSERT INTO orders (id, tenant_id, branch_id, order_code, pickup_at, created_by) "
                "VALUES (gen_random_uuid(), :t, :b, :oc, now(), :u) RETURNING id"
            ),
            {"t": str(tenant_id), "b": str(bid), "oc": f"{code}-0001", "u": str(user_id)},
        )
        await s.execute(
            text(
                "INSERT INTO order_items (id, order_id, service_name, quantity, unit_price, subtotal) "
                "VALUES (gen_random_uuid(), :o, :n, 1, 0, 0)"
            ),
            {"o": str(oid), "n": item_name},
        )
        await s.commit()


async def test_rls_child_table_isolated_via_parent(app_role_engine, owner, owner2):
    """order_items (KHÔNG có tenant_id) — policy GIÁN TIẾP qua orders.tenant_id.

    Context A → chỉ thấy item của đơn thuộc A (qua EXISTS parent)."""
    await _seed_order_item(owner["tenant_id"], owner["user_id"], "AA", "Item-A")
    await _seed_order_item(owner2["tenant_id"], owner2["user_id"], "BB", "Item-B")

    async with app_role_engine.connect() as conn:
        await conn.execute(text(_SET_TENANT), {"t": str(owner["tenant_id"])})
        rows = (await conn.execute(text("SELECT service_name FROM order_items"))).scalars().all()
        assert rows == ["Item-A"], f"child RLS leak: {rows!r}"
