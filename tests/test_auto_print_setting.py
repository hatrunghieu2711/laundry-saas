"""Stage 6.8.2 — auto_print_receipt per-tenant. Mặc định TRUE; owner PUT đổi được;
mọi role đọc qua GET /settings/pos."""
from httpx import AsyncClient

from tests.conftest import auth_headers, login


async def test_auto_print_default_true(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    r = await client.get("/api/v1/settings/pos", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    assert r.json()["auto_print_receipt"] is True  # mặc định = 2H behavior


async def test_owner_can_toggle_auto_print(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    r = await client.put("/api/v1/settings", json={"auto_print_receipt": False}, headers=auth_headers(t))
    assert r.status_code == 200, r.text
    assert r.json()["auto_print_receipt"] is False
    # đọc lại qua /pos
    pos = await client.get("/api/v1/settings/pos", headers=auth_headers(t))
    assert pos.json()["auto_print_receipt"] is False
    # bật lại
    r2 = await client.put("/api/v1/settings", json={"auto_print_receipt": True}, headers=auth_headers(t))
    assert r2.json()["auto_print_receipt"] is True


# ── auto_print_copy2 (liên 2) — TÁCH RIÊNG auto_print_receipt ────────────────
async def test_auto_print_copy2_default_true(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    r = await client.get("/api/v1/settings/pos", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    assert r.json()["auto_print_copy2"] is True  # mặc định = giữ hành vi (in liên 2)


async def test_owner_can_toggle_auto_print_copy2(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    # TÁCH RIÊNG: tắt liên 2, GIỮ bill bật.
    r = await client.put("/api/v1/settings", json={"auto_print_copy2": False}, headers=auth_headers(t))
    assert r.status_code == 200, r.text
    assert r.json()["auto_print_copy2"] is False
    assert r.json()["auto_print_receipt"] is True  # không đụng bill
    pos = await client.get("/api/v1/settings/pos", headers=auth_headers(t))
    assert pos.json()["auto_print_copy2"] is False
    assert pos.json()["auto_print_receipt"] is True


async def test_tenant_isolation_auto_print(client: AsyncClient, owner: dict, owner2: dict):
    t1 = await login(client, owner["phone"], owner["password"])
    await client.put("/api/v1/settings", json={"auto_print_receipt": False}, headers=auth_headers(t1))
    t2 = await login(client, owner2["phone"], owner2["password"])
    pos2 = await client.get("/api/v1/settings/pos", headers=auth_headers(t2))
    assert pos2.json()["auto_print_receipt"] is True  # tenant 2 không bị ảnh hưởng
