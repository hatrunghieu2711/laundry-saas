"""Test tenant_settings: default_turnaround_hours đọc/sửa + phân quyền.

POS đọc /settings/pos (mọi role), owner sửa /settings, staff bị 403.
"""
from httpx import AsyncClient

from tests.conftest import auth_headers, login

SETTINGS = "/api/v1/settings"


async def _staff_token(client: AsyncClient, owner_token: str) -> str:
    rb = await client.post("/api/v1/branches", json={"name": "CN A"},
                           headers=auth_headers(owner_token))
    branch = rb.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000061", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    return await login(client, "0900000061", "pass123")


async def test_pos_settings_default_turnaround(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    r = await client.get(f"{SETTINGS}/pos", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    assert r.json()["default_turnaround_hours"] == 4  # server_default


async def test_owner_update_turnaround(client: AsyncClient, owner: dict):
    t = await login(client, owner["phone"], owner["password"])
    upd = await client.put(SETTINGS, json={"default_turnaround_hours": 6},
                           headers=auth_headers(t))
    assert upd.status_code == 200, upd.text
    assert upd.json()["default_turnaround_hours"] == 6
    # đọc lại từ endpoint POS.
    pos = await client.get(f"{SETTINGS}/pos", headers=auth_headers(t))
    assert pos.json()["default_turnaround_hours"] == 6
    # full settings: secret telegram mặc định None.
    full = await client.get(SETTINGS, headers=auth_headers(t))
    assert full.json()["telegram_bot_token"] is None


async def test_staff_can_read_pos_cannot_update(client: AsyncClient, owner: dict):
    owner_token = await login(client, owner["phone"], owner["password"])
    staff = await _staff_token(client, owner_token)
    # staff đọc được /pos
    ok = await client.get(f"{SETTINGS}/pos", headers=auth_headers(staff))
    assert ok.status_code == 200
    # staff không sửa được
    bad = await client.put(SETTINGS, json={"default_turnaround_hours": 8},
                           headers=auth_headers(staff))
    assert bad.status_code == 403
    # staff không đọc được full settings (chứa secret)
    full = await client.get(SETTINGS, headers=auth_headers(staff))
    assert full.status_code == 403


async def test_settings_tenant_isolation(client: AsyncClient, owner: dict, owner2: dict):
    t1 = await login(client, owner["phone"], owner["password"])
    await client.put(SETTINGS, json={"default_turnaround_hours": 9}, headers=auth_headers(t1))
    t2 = await login(client, owner2["phone"], owner2["password"])
    pos2 = await client.get(f"{SETTINGS}/pos", headers=auth_headers(t2))
    assert pos2.json()["default_turnaround_hours"] == 4  # tenant 2 không bị ảnh hưởng
