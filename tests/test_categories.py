"""Test danh mục dịch vụ (categories) — Stage 4.3. Viết TRƯỚC service (TDD).

Bao phủ: CRUD, sắp thứ tự (reorder), chặn xóa danh mục còn dịch vụ đang dùng,
service tham chiếu category_id (ServiceOut trả kèm category info), tenant isolation.
"""
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import auth_headers, login

CATEGORIES = "/api/v1/categories"
SERVICES = "/api/v1/services"


@pytest_asyncio.fixture
async def cctx(client: AsyncClient, owner: dict) -> dict:
    owner_token = await login(client, owner["phone"], owner["password"])
    rb = await client.post("/api/v1/branches", json={"name": "CN A"},
                           headers=auth_headers(owner_token))
    branch_a = rb.json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000091", "password": "pass123",
              "role": "staff", "branch_id": branch_a["id"]},
        headers=auth_headers(owner_token),
    )
    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_token": await login(client, "0900000091", "pass123"),
        "branch_a": branch_a,
    }


async def _create_cat(client, token, **body) -> dict:
    return await client.post(CATEGORIES, json=body, headers=auth_headers(token))


# ── CRUD ──────────────────────────────────────────────────────────────────────
async def test_create_category(client: AsyncClient, cctx: dict):
    r = await _create_cat(client, cctx["owner_token"], name="Giặt sấy", icon="🧺",
                          display_order=0)
    assert r.status_code == 201, r.text
    c = r.json()
    assert c["name"] == "Giặt sấy"
    assert c["icon"] == "🧺"
    assert c["display_order"] == 0
    assert c["is_active"] is True


async def test_staff_cannot_write_can_read(client: AsyncClient, cctx: dict):
    # staff không tạo được.
    r = await _create_cat(client, cctx["staff_token"], name="X", icon="👕")
    assert r.status_code == 403
    # owner tạo, staff đọc được.
    await _create_cat(client, cctx["owner_token"], name="Đồ lẻ", icon="👕")
    lst = await client.get(CATEGORIES, headers=auth_headers(cctx["staff_token"]))
    assert lst.status_code == 200
    assert lst.json()["total"] == 1


async def test_list_ordered_by_display_order(client: AsyncClient, cctx: dict):
    await _create_cat(client, cctx["owner_token"], name="B", icon="👕", display_order=2)
    await _create_cat(client, cctx["owner_token"], name="A", icon="🧺", display_order=1)
    lst = await client.get(CATEGORIES, headers=auth_headers(cctx["owner_token"]))
    names = [c["name"] for c in lst.json()["items"]]
    assert names == ["A", "B"]


async def test_update_category(client: AsyncClient, cctx: dict):
    c = (await _create_cat(client, cctx["owner_token"], name="Giặt", icon="🧺")).json()
    upd = await client.put(f"{CATEGORIES}/{c['id']}",
                           json={"name": "Giặt sấy", "icon": "🧥"},
                           headers=auth_headers(cctx["owner_token"]))
    assert upd.status_code == 200, upd.text
    assert upd.json()["name"] == "Giặt sấy"
    assert upd.json()["icon"] == "🧥"


async def test_reorder_categories(client: AsyncClient, cctx: dict):
    a = (await _create_cat(client, cctx["owner_token"], name="A", display_order=0)).json()
    b = (await _create_cat(client, cctx["owner_token"], name="B", display_order=1)).json()
    cc = (await _create_cat(client, cctx["owner_token"], name="C", display_order=2)).json()
    # đảo lại: C, A, B
    r = await client.put(f"{CATEGORIES}/reorder",
                         json={"ids": [cc["id"], a["id"], b["id"]]},
                         headers=auth_headers(cctx["owner_token"]))
    assert r.status_code == 200, r.text
    lst = await client.get(CATEGORIES, headers=auth_headers(cctx["owner_token"]))
    assert [c["name"] for c in lst.json()["items"]] == ["C", "A", "B"]


# ── soft delete + chặn xóa khi còn dịch vụ ───────────────────────────────────
async def test_delete_empty_category_ok(client: AsyncClient, cctx: dict):
    c = (await _create_cat(client, cctx["owner_token"], name="Trống", icon="📦")).json()
    d = await client.delete(f"{CATEGORIES}/{c['id']}",
                            headers=auth_headers(cctx["owner_token"]))
    assert d.status_code == 200
    assert d.json()["is_active"] is False
    # mặc định list chỉ trả active.
    lst = await client.get(CATEGORIES, headers=auth_headers(cctx["owner_token"]))
    assert lst.json()["total"] == 0
    lst2 = await client.get(f"{CATEGORIES}?include_inactive=true",
                            headers=auth_headers(cctx["owner_token"]))
    assert lst2.json()["total"] == 1


async def test_delete_category_in_use_blocked(client: AsyncClient, cctx: dict):
    cat = (await _create_cat(client, cctx["owner_token"], name="Đồ lẻ", icon="👕")).json()
    svc = await client.post(
        SERVICES,
        json={"name": "Áo Vest", "unit": "cai", "pricing_type": "per_unit",
              "unit_price": 60000, "category_id": cat["id"]},
        headers=auth_headers(cctx["owner_token"]),
    )
    assert svc.status_code == 201, svc.text

    d = await client.delete(f"{CATEGORIES}/{cat['id']}",
                            headers=auth_headers(cctx["owner_token"]))
    assert d.status_code == 409
    body = d.json()
    assert body["code"] == "CATEGORY_IN_USE"
    assert "1" in body["message"]  # "còn 1 dịch vụ..."

    # Ẩn dịch vụ -> danh mục không còn dịch vụ active -> xóa được.
    await client.delete(f"{SERVICES}/{svc.json()['id']}",
                        headers=auth_headers(cctx["owner_token"]))
    d2 = await client.delete(f"{CATEGORIES}/{cat['id']}",
                             headers=auth_headers(cctx["owner_token"]))
    assert d2.status_code == 200
    assert d2.json()["is_active"] is False


# ── service tham chiếu category_id ───────────────────────────────────────────
async def test_service_with_category_id_returns_nested(client: AsyncClient, cctx: dict):
    cat = (await _create_cat(client, cctx["owner_token"], name="Đồ lẻ", icon="👕")).json()
    r = await client.post(
        SERVICES,
        json={"name": "Áo sơ mi", "unit": "cai", "pricing_type": "per_unit",
              "unit_price": 15000, "category_id": cat["id"]},
        headers=auth_headers(cctx["owner_token"]),
    )
    assert r.status_code == 201, r.text
    svc = r.json()
    assert svc["category_id"] == cat["id"]
    assert svc["category"]["name"] == "Đồ lẻ"
    assert svc["category"]["icon"] == "👕"

    # Không gửi category_id -> null.
    plain = await client.post(
        SERVICES,
        json={"name": "Khăn", "unit": "cai", "pricing_type": "per_unit", "unit_price": 5000},
        headers=auth_headers(cctx["owner_token"]),
    )
    assert plain.status_code == 201, plain.text
    assert plain.json()["category_id"] is None
    assert plain.json()["category"] is None


async def test_service_invalid_category_id_rejected(client: AsyncClient, cctx: dict):
    import uuid
    r = await client.post(
        SERVICES,
        json={"name": "X", "unit": "cai", "pricing_type": "per_unit",
              "unit_price": 1000, "category_id": str(uuid.uuid4())},
        headers=auth_headers(cctx["owner_token"]),
    )
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_CATEGORY"


async def test_service_category_from_other_tenant_rejected(
    client: AsyncClient, cctx: dict, owner2: dict
):
    cat = (await _create_cat(client, cctx["owner_token"], name="Đồ lẻ")).json()
    other = await login(client, owner2["phone"], owner2["password"])
    r = await client.post(
        SERVICES,
        json={"name": "X", "unit": "cai", "pricing_type": "per_unit",
              "unit_price": 1000, "category_id": cat["id"]},
        headers=auth_headers(other),
    )
    assert r.status_code == 422
    assert r.json()["code"] == "INVALID_CATEGORY"


# ── tenant isolation ─────────────────────────────────────────────────────────
async def test_category_tenant_isolation(client: AsyncClient, cctx: dict, owner2: dict):
    cat = (await _create_cat(client, cctx["owner_token"], name="Đồ lẻ")).json()
    other = await login(client, owner2["phone"], owner2["password"])

    lst = await client.get(CATEGORIES, headers=auth_headers(other))
    assert lst.status_code == 200 and lst.json()["total"] == 0
    got = await client.get(f"{CATEGORIES}/{cat['id']}", headers=auth_headers(other))
    assert got.status_code == 404
    upd = await client.put(f"{CATEGORIES}/{cat['id']}", json={"name": "Hack"},
                           headers=auth_headers(other))
    assert upd.status_code == 404
