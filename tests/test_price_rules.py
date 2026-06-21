"""Test price_rules: CRUD owner + áp dụng theo ngày (Stage 5.4). Viết TRƯỚC (TDD).

Quy tắc tự áp khi tạo đơn (xem test_order_adjustments). Ở đây test:
- owner CRUD; staff KHÔNG ghi được.
- validate khoảng ngày (end >= start).
- GET /price-rules/applicable trả rule surcharge + discount đang hiệu lực HÔM NAY
  (giờ VN), bỏ rule ngoài khoảng / đã ẩn.
"""
from datetime import datetime, timedelta, timezone

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from tests.conftest import auth_headers, login

RULES = "/api/v1/price-rules"


def _vn_today():
    return (datetime.now(timezone.utc) + timedelta(hours=7)).date()


def _rule_body(**over) -> dict:
    today = _vn_today()
    body = {
        "type": "surcharge",
        "value_type": "percent",
        "value": 20,
        "name": "Phụ thu Tết",
        "start_date": (today - timedelta(days=1)).isoformat(),
        "end_date": (today + timedelta(days=1)).isoformat(),
    }
    body.update(over)
    return body


@pytest_asyncio.fixture
async def rctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    r = await client.post("/api/v1/branches", json={"name": "CN A"},
                          headers=auth_headers(owner_token))
    branch = r.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000051", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    staff_token = await login(client, "0900000051", "pass123")
    return {"owner": owner, "owner_token": owner_token, "staff_token": staff_token, "branch": branch}


async def test_owner_crud_rule(client: AsyncClient, rctx: dict):
    t = rctx["owner_token"]
    r = await client.post(RULES, json=_rule_body(), headers=auth_headers(t))
    assert r.status_code == 201, r.text
    rule = r.json()
    rid = rule["id"]
    assert rule["type"] == "surcharge" and rule["value_type"] == "percent"
    assert rule["is_active"] is True

    lst = await client.get(RULES, headers=auth_headers(t))
    assert lst.status_code == 200
    assert any(x["id"] == rid for x in lst.json()["items"])

    up = await client.put(f"{RULES}/{rid}", json={"value": 10, "name": "Phụ thu lễ"},
                          headers=auth_headers(t))
    assert up.status_code == 200
    assert int(float(up.json()["value"])) == 10
    assert up.json()["name"] == "Phụ thu lễ"

    d = await client.delete(f"{RULES}/{rid}", headers=auth_headers(t))
    assert d.status_code == 200
    # Hard delete (Stage fix): rule BIẾN MẤT khỏi list (không còn row).
    lst2 = await client.get(RULES, headers=auth_headers(t))
    assert not any(x["id"] == rid for x in lst2.json()["items"])


async def test_staff_cannot_write_rule(client: AsyncClient, rctx: dict):
    bad = await client.post(RULES, json=_rule_body(), headers=auth_headers(rctx["staff_token"]))
    assert bad.status_code == 403


async def test_invalid_date_range(client: AsyncClient, rctx: dict):
    today = _vn_today()
    body = _rule_body(start_date=today.isoformat(),
                      end_date=(today - timedelta(days=2)).isoformat())
    r = await client.post(RULES, json=body, headers=auth_headers(rctx["owner_token"]))
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_DATE_RANGE"


async def test_applicable_today(client: AsyncClient, rctx: dict):
    t = rctx["owner_token"]
    today = _vn_today()
    await client.post(RULES, json=_rule_body(type="surcharge", value=20),
                      headers=auth_headers(t))
    await client.post(RULES, json=_rule_body(type="discount", value_type="fixed",
                      value=10000, name="Giảm khai trương"), headers=auth_headers(t))
    # rule quá khứ — KHÔNG áp.
    await client.post(RULES, json=_rule_body(
        type="surcharge", value=99, name="cũ",
        start_date=(today - timedelta(days=10)).isoformat(),
        end_date=(today - timedelta(days=5)).isoformat()), headers=auth_headers(t))

    # staff đọc được applicable (để POS điền sẵn).
    appl = await client.get(f"{RULES}/applicable", headers=auth_headers(rctx["staff_token"]))
    assert appl.status_code == 200, appl.text
    data = appl.json()
    assert data["surcharge"] is not None and int(float(data["surcharge"]["value"])) == 20
    assert data["discount"] is not None and data["discount"]["value_type"] == "fixed"


async def test_applicable_none_when_no_rule(client: AsyncClient, rctx: dict):
    appl = await client.get(f"{RULES}/applicable", headers=auth_headers(rctx["owner_token"]))
    assert appl.status_code == 200
    assert appl.json()["surcharge"] is None
    assert appl.json()["discount"] is None


async def test_rule_tenant_isolation(client: AsyncClient, rctx: dict, owner2: dict):
    await client.post(RULES, json=_rule_body(), headers=auth_headers(rctx["owner_token"]))
    t2 = await login(client, owner2["phone"], owner2["password"])
    appl = await client.get(f"{RULES}/applicable", headers=auth_headers(t2))
    assert appl.json()["surcharge"] is None  # tenant 2 không thấy rule tenant 1


# ── Xóa = HARD delete (fix bug "Xóa trùng Ẩn") ──────────────────────────────
async def test_delete_hidden_rule_also_removed(client: AsyncClient, rctx: dict):
    """⭐ Bug GỐC: rule ĐÃ ẩn (is_active=false) → bấm Xóa vẫn phải mất khỏi list."""
    t = rctx["owner_token"]
    rid = (await client.post(RULES, json=_rule_body(), headers=auth_headers(t))).json()["id"]
    # Ẩn (tắt) trước
    await client.put(f"{RULES}/{rid}", json={"is_active": False}, headers=auth_headers(t))
    lst = await client.get(RULES, headers=auth_headers(t))
    assert any(x["id"] == rid for x in lst.json()["items"])  # vẫn còn (đã ẩn)
    # Xóa → mất hẳn
    assert (await client.delete(f"{RULES}/{rid}", headers=auth_headers(t))).status_code == 200
    lst2 = await client.get(RULES, headers=auth_headers(t))
    assert not any(x["id"] == rid for x in lst2.json()["items"])


async def test_toggle_active_keeps_rule(client: AsyncClient, rctx: dict):
    """Ẩn/Bật (PUT is_active) KHÔNG xóa — rule vẫn trong list, bật lại được."""
    t = rctx["owner_token"]
    rid = (await client.post(RULES, json=_rule_body(), headers=auth_headers(t))).json()["id"]
    off = await client.put(f"{RULES}/{rid}", json={"is_active": False}, headers=auth_headers(t))
    assert off.json()["is_active"] is False
    assert any(x["id"] == rid for x in (await client.get(RULES, headers=auth_headers(t))).json()["items"])
    on = await client.put(f"{RULES}/{rid}", json={"is_active": True}, headers=auth_headers(t))
    assert on.json()["is_active"] is True


async def test_delete_other_tenant_rule_404(client: AsyncClient, rctx: dict, owner2: dict):
    """Tenant khác KHÔNG xóa được rule (get_rule lọc tenant → 404)."""
    rid = (await client.post(RULES, json=_rule_body(), headers=auth_headers(rctx["owner_token"]))).json()["id"]
    t2 = await login(client, owner2["phone"], owner2["password"])
    assert (await client.delete(f"{RULES}/{rid}", headers=auth_headers(t2))).status_code == 404


async def _seed_rule(tenant_id, name):
    async with SessionFactory() as s:
        rid = await s.scalar(
            text(
                "INSERT INTO price_rules (id, tenant_id, type, value_type, value, name, "
                "start_date, end_date, is_active) VALUES (gen_random_uuid(), :t, 'surcharge', "
                "'percent', 10, :n, '2026-01-01', '2026-12-31', true) RETURNING id"
            ),
            {"t": str(tenant_id), "n": name},
        )
        await s.commit()
        return rid


async def test_rls_delete_isolation(app_role_engine, owner: dict, owner2: dict):
    """⭐ RLS: context tenant A → DELETE chỉ xóa rule của A; rule tenant B sống."""
    a = await _seed_rule(owner["tenant_id"], "A")
    b = await _seed_rule(owner2["tenant_id"], "B")
    async with app_role_engine.connect() as conn:
        await conn.execute(
            text("SELECT set_config('app.current_tenant_id', :t, false)"),
            {"t": str(owner["tenant_id"])},
        )
        await conn.execute(text("DELETE FROM price_rules"))  # RLS: chỉ thấy/xóa của A
        await conn.commit()
    async with SessionFactory() as s:  # owner engine bypass → kiểm thực
        na = await s.scalar(text("SELECT count(*) FROM price_rules WHERE id = :i"), {"i": str(a)})
        nb = await s.scalar(text("SELECT count(*) FROM price_rules WHERE id = :i"), {"i": str(b)})
    assert na == 0 and nb == 1, f"RLS delete leak: A={na} B={nb}"


async def test_old_order_keeps_snapshot_after_rule_delete(client: AsyncClient, rctx: dict):
    """Xóa rule KHÔNG đụng đơn cũ (snapshot surcharge_amount/reason; 0 FK → đơn cũ nguyên)."""
    t = rctx["owner_token"]
    rid = (await client.post(RULES, json=_rule_body(name="Phụ thu Tết"), headers=auth_headers(t))).json()["id"]
    async with SessionFactory() as s:  # đơn có phụ thu snapshot (owner bypass)
        oid = await s.scalar(
            text(
                "INSERT INTO orders (id, tenant_id, branch_id, order_code, pickup_at, created_by, "
                "subtotal, surcharge_amount, total_amount, surcharge_reason) VALUES "
                "(gen_random_uuid(), :t, :b, 'PR-0001', now(), :u, 100000, 20000, 120000, 'Phụ thu Tết') "
                "RETURNING id"
            ),
            {"t": str(rctx["owner"]["tenant_id"]), "b": rctx["branch"]["id"], "u": str(rctx["owner"]["user_id"])},
        )
        await s.commit()
    assert (await client.delete(f"{RULES}/{rid}", headers=auth_headers(t))).status_code == 200
    async with SessionFactory() as s:
        row = (await s.execute(
            text("SELECT surcharge_amount, surcharge_reason FROM orders WHERE id = :i"), {"i": str(oid)}
        )).first()
    assert int(row[0]) == 20000 and row[1] == "Phụ thu Tết"
