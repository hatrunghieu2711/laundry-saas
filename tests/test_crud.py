"""Test CRUD tenants/branches/users + phân quyền role + cách ly multi-tenant."""
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from app.models.shift import Shift
from tests.conftest import auth_headers, login

TENANTS = "/api/v1/tenants"
BRANCHES = "/api/v1/branches"
USERS = "/api/v1/users"


@pytest_asyncio.fixture
async def org(client: AsyncClient, owner: dict) -> dict:
    """Owner đăng nhập, tạo branch B1 + 1 manager + 1 staff (đều ở B1).

    Trả token của từng role + id branch để các test phân quyền dùng lại.
    """
    owner_token = await login(client, owner["phone"], owner["password"])

    r = await client.post(
        BRANCHES, json={"name": "CN Trung Tâm"}, headers=auth_headers(owner_token)
    )
    assert r.status_code == 201, r.text
    branch = r.json()

    async def _make(role: str, phone: str) -> None:
        resp = await client.post(
            USERS,
            json={
                "full_name": f"{role} 1",
                "phone": phone,
                "password": "pass123",
                "role": role,
                "branch_id": branch["id"],
            },
            headers=auth_headers(owner_token),
        )
        assert resp.status_code == 201, resp.text

    await _make("manager", "0900000010")
    await _make("staff", "0900000011")

    return {
        "owner": owner,
        "owner_token": owner_token,
        "manager_token": await login(client, "0900000010", "pass123"),
        "staff_token": await login(client, "0900000011", "pass123"),
        "branch": branch,
    }


# ── tenants ───────────────────────────────────────────────────────────────
async def test_post_tenants_forbidden(client: AsyncClient, org: dict):
    resp = await client.post(
        TENANTS, json={"name": "X"}, headers=auth_headers(org["owner_token"])
    )
    assert resp.status_code == 403
    assert resp.json()["code"] == "FEATURE_NOT_AVAILABLE"


async def test_get_own_tenant(client: AsyncClient, org: dict):
    tid = str(org["owner"]["tenant_id"])
    resp = await client.get(f"{TENANTS}/{tid}", headers=auth_headers(org["staff_token"]))
    assert resp.status_code == 200
    assert resp.json()["id"] == tid


async def test_get_other_tenant_forbidden(client: AsyncClient, org: dict, owner2: dict):
    other = str(owner2["tenant_id"])
    resp = await client.get(f"{TENANTS}/{other}", headers=auth_headers(org["owner_token"]))
    assert resp.status_code == 403
    assert resp.json()["code"] == "FORBIDDEN"


async def test_owner_updates_tenant(client: AsyncClient, org: dict):
    tid = str(org["owner"]["tenant_id"])
    resp = await client.patch(
        f"{TENANTS}/{tid}", json={"name": "Giặt Ủi 2H Mới"},
        headers=auth_headers(org["owner_token"]),
    )
    assert resp.status_code == 200
    assert resp.json()["name"] == "Giặt Ủi 2H Mới"


async def test_manager_cannot_update_tenant(client: AsyncClient, org: dict):
    tid = str(org["owner"]["tenant_id"])
    resp = await client.patch(
        f"{TENANTS}/{tid}", json={"name": "Hack"},
        headers=auth_headers(org["manager_token"]),
    )
    assert resp.status_code == 403


# ── branches: tạo + auto code + sequence ────────────────────────────────────
async def test_create_branch_auto_code_and_sequence(client: AsyncClient, owner: dict):
    token = await login(client, owner["phone"], owner["password"])
    r1 = await client.post(BRANCHES, json={"name": "CN 1"}, headers=auth_headers(token))
    r2 = await client.post(BRANCHES, json={"name": "CN 2"}, headers=auth_headers(token))
    assert r1.json()["code"] == "B1"
    assert r2.json()["code"] == "B2"

    # Sequence per-tenant: order_code_seq_{tenant_hex}_b1 / _b2 phải tồn tại.
    async with SessionFactory() as db:
        thex = owner["tenant_id"].hex
        for code in ("b1", "b2"):
            name = f"order_code_seq_{thex}_{code}"
            exists = await db.scalar(
                text("SELECT 1 FROM pg_class WHERE relkind='S' AND relname=:n"),
                {"n": name},
            )
            assert exists == 1, f"thiếu sequence {name}"


# ── branches: phân quyền ────────────────────────────────────────────────────
async def test_manager_cannot_create_branch(client: AsyncClient, org: dict):
    resp = await client.post(
        BRANCHES, json={"name": "CN lén"}, headers=auth_headers(org["manager_token"])
    )
    assert resp.status_code == 403


async def test_staff_cannot_create_branch(client: AsyncClient, org: dict):
    resp = await client.post(
        BRANCHES, json={"name": "CN lén"}, headers=auth_headers(org["staff_token"])
    )
    assert resp.status_code == 403


async def test_manager_can_list_branches(client: AsyncClient, org: dict):
    resp = await client.get(BRANCHES, headers=auth_headers(org["manager_token"]))
    assert resp.status_code == 200
    assert resp.json()["total"] == 1


async def test_staff_sees_only_own_branch(client: AsyncClient, org: dict):
    # Owner tạo thêm branch thứ 2; staff (ở B1) vẫn chỉ thấy 1.
    await client.post(BRANCHES, json={"name": "CN 2"}, headers=auth_headers(org["owner_token"]))
    resp = await client.get(BRANCHES, headers=auth_headers(org["staff_token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["id"] == org["branch"]["id"]


# ── branches: soft delete + chặn khi còn shift open ────────────────────────
async def test_soft_delete_branch(client: AsyncClient, org: dict):
    bid = org["branch"]["id"]
    resp = await client.delete(f"{BRANCHES}/{bid}", headers=auth_headers(org["owner_token"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"
    # Dòng vẫn còn trong DB (soft delete), không bị xóa cứng.
    async with SessionFactory() as db:
        still = await db.scalar(text("SELECT count(*) FROM branches WHERE id=:i"), {"i": bid})
        assert still == 1


async def test_cannot_delete_branch_with_open_shift(client: AsyncClient, org: dict):
    bid = org["branch"]["id"]
    async with SessionFactory() as db:
        db.add(
            Shift(
                tenant_id=org["owner"]["tenant_id"],
                branch_id=bid,
                opened_by=org["owner"]["user_id"],
                opening_cash=0,
                status="open",
            )
        )
        await db.commit()
    resp = await client.delete(f"{BRANCHES}/{bid}", headers=auth_headers(org["owner_token"]))
    assert resp.status_code == 409
    assert resp.json()["code"] == "BRANCH_HAS_OPEN_SHIFT"


# ── users: phân quyền tạo ───────────────────────────────────────────────────
async def test_owner_creates_user(client: AsyncClient, org: dict):
    resp = await client.post(
        USERS,
        json={
            "full_name": "Shipper A", "phone": "0900000020",
            "password": "pass123", "role": "shipper", "branch_id": org["branch"]["id"],
        },
        headers=auth_headers(org["owner_token"]),
    )
    assert resp.status_code == 201
    assert resp.json()["role"] == "shipper"
    assert "password_hash" not in resp.json()


async def test_manager_creates_staff(client: AsyncClient, org: dict):
    resp = await client.post(
        USERS,
        json={
            "full_name": "Staff 2", "phone": "0900000021",
            "password": "pass123", "role": "staff",
        },
        headers=auth_headers(org["manager_token"]),
    )
    assert resp.status_code == 201
    # Manager bị ép branch về branch của mình.
    assert resp.json()["branch_id"] == org["branch"]["id"]


async def test_manager_cannot_create_owner(client: AsyncClient, org: dict):
    resp = await client.post(
        USERS,
        json={
            "full_name": "Owner lén", "phone": "0900000022",
            "password": "pass123", "role": "owner",
        },
        headers=auth_headers(org["manager_token"]),
    )
    assert resp.status_code == 403


async def test_staff_cannot_list_users(client: AsyncClient, org: dict):
    resp = await client.get(USERS, headers=auth_headers(org["staff_token"]))
    assert resp.status_code == 403


# ── users: KHÔNG ai sửa được role của owner ────────────────────────────────
async def test_cannot_change_owner_role(client: AsyncClient, org: dict):
    owner_id = str(org["owner"]["user_id"])
    resp = await client.patch(
        f"{USERS}/{owner_id}", json={"role": "staff"},
        headers=auth_headers(org["owner_token"]),
    )
    assert resp.status_code == 403


# ── users: soft delete ──────────────────────────────────────────────────────
async def test_soft_delete_user(client: AsyncClient, org: dict):
    # Lấy id staff qua list (owner).
    listing = await client.get(USERS, headers=auth_headers(org["owner_token"]))
    staff = next(u for u in listing.json()["items"] if u["role"] == "staff")
    resp = await client.delete(f"{USERS}/{staff['id']}", headers=auth_headers(org["owner_token"]))
    assert resp.status_code == 200
    assert resp.json()["status"] == "inactive"
    async with SessionFactory() as db:
        still = await db.scalar(text("SELECT count(*) FROM users WHERE id=:i"), {"i": staff["id"]})
        assert still == 1


# ── multi-tenant isolation ──────────────────────────────────────────────────
async def test_cross_tenant_branch_isolation(client: AsyncClient, org: dict, owner2: dict):
    other_token = await login(client, owner2["phone"], owner2["password"])
    bid = org["branch"]["id"]  # branch của tenant 1
    resp = await client.get(f"{BRANCHES}/{bid}", headers=auth_headers(other_token))
    assert resp.status_code == 404
    assert resp.json()["code"] == "BRANCH_NOT_FOUND"


async def test_cross_tenant_user_isolation(client: AsyncClient, org: dict, owner2: dict):
    other_token = await login(client, owner2["phone"], owner2["password"])
    uid = str(org["owner"]["user_id"])  # user của tenant 1
    resp = await client.get(f"{USERS}/{uid}", headers=auth_headers(other_token))
    assert resp.status_code == 404
    assert resp.json()["code"] == "USER_NOT_FOUND"


async def test_cross_tenant_list_isolation(client: AsyncClient, org: dict, owner2: dict):
    """Owner tenant 2 list branches: chỉ thấy của tenant mình (0), không thấy tenant 1."""
    other_token = await login(client, owner2["phone"], owner2["password"])
    resp = await client.get(BRANCHES, headers=auth_headers(other_token))
    assert resp.status_code == 200
    assert resp.json()["total"] == 0


# ── pagination ──────────────────────────────────────────────────────────────
async def test_pagination_limit(client: AsyncClient, org: dict):
    # org đã có owner + manager + staff = 3 user. limit=2 -> 2 item, total=3.
    resp = await client.get(
        f"{USERS}?limit=2&offset=0", headers=auth_headers(org["owner_token"])
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 3
    assert len(body["items"]) == 2
    assert body["limit"] == 2


async def test_pagination_limit_clamped(client: AsyncClient, org: dict):
    resp = await client.get(
        f"{USERS}?limit=9999", headers=auth_headers(org["owner_token"])
    )
    assert resp.status_code == 200
    assert resp.json()["limit"] == 200  # clamp về max 200
