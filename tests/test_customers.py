"""Test customer endpoints: tạo nhanh (chỉ phone), tìm theo phone, cách ly tenant."""
import pytest_asyncio
from httpx import AsyncClient
from tests.conftest import auth_headers, login

CUSTOMERS = "/api/v1/customers"


@pytest_asyncio.fixture
async def cctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    branch = (await client.post("/api/v1/branches", json={"name": "CN A"},
                                headers=auth_headers(owner_token))).json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000071", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    return {"owner_token": owner_token, "staff_token": await login(client, "0900000071", "pass123")}


async def test_quick_create_phone_only(client: AsyncClient, cctx: dict):
    # Tạo nhanh chỉ với phone — full_name tự điền = phone.
    resp = await client.post(CUSTOMERS, json={"phone": "0987654321"},
                             headers=auth_headers(cctx["staff_token"]))
    assert resp.status_code == 201, resp.text
    assert resp.json()["phone"] == "0987654321"
    assert resp.json()["full_name"] == "0987654321"


async def test_create_with_name(client: AsyncClient, cctx: dict):
    resp = await client.post(CUSTOMERS, json={"full_name": "Chị Lan", "phone": "0911222333"},
                             headers=auth_headers(cctx["staff_token"]))
    assert resp.status_code == 201
    assert resp.json()["full_name"] == "Chị Lan"


async def test_find_by_phone(client: AsyncClient, cctx: dict):
    await client.post(CUSTOMERS, json={"phone": "0900111222"},
                      headers=auth_headers(cctx["staff_token"]))
    found = await client.get(f"{CUSTOMERS}?phone=0900111222", headers=auth_headers(cctx["staff_token"]))
    assert found.status_code == 200
    assert found.json()["total"] == 1
    # phone không tồn tại -> rỗng
    none = await client.get(f"{CUSTOMERS}?phone=0000000000", headers=auth_headers(cctx["staff_token"]))
    assert none.json()["total"] == 0


async def test_cross_tenant_isolation(client: AsyncClient, cctx: dict, owner2: dict):
    made = await client.post(CUSTOMERS, json={"phone": "0900111999"},
                             headers=auth_headers(cctx["staff_token"]))
    cid = made.json()["id"]
    other = await login(client, owner2["phone"], owner2["password"])
    got = await client.get(f"{CUSTOMERS}/{cid}", headers=auth_headers(other))
    assert got.status_code == 404
    lst = await client.get(f"{CUSTOMERS}?phone=0900111999", headers=auth_headers(other))
    assert lst.json()["total"] == 0
