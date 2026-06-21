"""Test quản lý tài khoản nhân viên (Stage 5.5). Viết TRƯỚC (TDD).

Phân quyền theo role + branch:
- owner: quản lý mọi user trong tenant; manager: chỉ staff/shipper branch mình.
- reset password, khóa (suspended)/mở (active), KHÔNG tự khóa mình.
- Khóa thì login bị từ chối. Tenant isolation. List kèm branch_name + in_open_shift.
Tài khoản theo ca (phone = "nv_ca_sang") là hợp lệ — login bằng chuỗi đó.
"""
import pytest_asyncio
from httpx import AsyncClient

from tests.conftest import auth_headers, login

USERS = "/api/v1/users"
BRANCHES = "/api/v1/branches"


@pytest_asyncio.fixture
async def umctx(client: AsyncClient, owner: dict) -> dict:
    """owner + branch A/B + manager(A) + staff(A) + staff(B)."""
    owner_token = await login(client, owner["phone"], owner["password"])

    async def _branch(name: str) -> dict:
        r = await client.post(BRANCHES, json={"name": name}, headers=auth_headers(owner_token))
        assert r.status_code == 201, r.text
        return r.json()

    branch_a = await _branch("CN A")
    branch_b = await _branch("CN B")

    async def _user(role: str, phone: str, branch: dict) -> dict:
        r = await client.post(USERS, json={
            "full_name": f"{role} {phone[-2:]}", "phone": phone, "password": "pass123",
            "role": role, "branch_id": branch["id"],
        }, headers=auth_headers(owner_token))
        assert r.status_code == 201, r.text
        return r.json()

    manager_a = await _user("manager", "0900000070", branch_a)
    staff_a = await _user("staff", "0900000071", branch_a)
    staff_b = await _user("staff", "0900000072", branch_b)

    return {
        "owner": owner,
        "owner_token": owner_token,
        "manager_token": await login(client, "0900000070", "pass123"),
        "staff_token": await login(client, "0900000071", "pass123"),
        "branch_a": branch_a,
        "branch_b": branch_b,
        "manager_a": manager_a,
        "staff_a": staff_a,
        "staff_b": staff_b,
    }


# ── reset password ───────────────────────────────────────────────────────────
async def test_owner_resets_password(client: AsyncClient, umctx: dict):
    uid = umctx["staff_a"]["id"]
    r = await client.post(f"{USERS}/{uid}/reset-password", json={"password": "newpass1"},
                          headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 200, r.text
    # mật khẩu mới đăng nhập được; mật khẩu cũ thì không.
    ok = await client.post("/api/v1/auth/login", json={"phone": "0900000071", "password": "newpass1"})
    assert ok.status_code == 200
    bad = await client.post("/api/v1/auth/login", json={"phone": "0900000071", "password": "pass123"})
    assert bad.status_code == 401


async def test_manager_resets_staff_in_branch(client: AsyncClient, umctx: dict):
    uid = umctx["staff_a"]["id"]
    r = await client.post(f"{USERS}/{uid}/reset-password", json={"password": "mgrset1"},
                          headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 200, r.text


async def test_manager_cannot_reset_other_branch_staff(client: AsyncClient, umctx: dict):
    uid = umctx["staff_b"]["id"]  # branch B
    r = await client.post(f"{USERS}/{uid}/reset-password", json={"password": "x123456"},
                          headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 403


async def test_manager_cannot_reset_owner_password(client: AsyncClient, umctx: dict):
    uid = umctx["owner"]["user_id"]
    r = await client.post(f"{USERS}/{uid}/reset-password", json={"password": "x123456"},
                          headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 403


# ── khóa / mở (status) ───────────────────────────────────────────────────────
async def test_owner_suspend_blocks_login_then_unsuspend(client: AsyncClient, umctx: dict):
    uid = umctx["staff_a"]["id"]
    sus = await client.patch(f"{USERS}/{uid}/status", json={"status": "suspended"},
                             headers=auth_headers(umctx["owner_token"]))
    assert sus.status_code == 200, sus.text
    assert sus.json()["status"] == "suspended"
    # bị khóa → login từ chối.
    bad = await client.post("/api/v1/auth/login", json={"phone": "0900000071", "password": "pass123"})
    assert bad.status_code == 401
    # mở lại → login được.
    act = await client.patch(f"{USERS}/{uid}/status", json={"status": "active"},
                             headers=auth_headers(umctx["owner_token"]))
    assert act.status_code == 200 and act.json()["status"] == "active"
    ok = await client.post("/api/v1/auth/login", json={"phone": "0900000071", "password": "pass123"})
    assert ok.status_code == 200


async def test_cannot_suspend_self(client: AsyncClient, umctx: dict):
    uid = umctx["owner"]["user_id"]
    r = await client.patch(f"{USERS}/{uid}/status", json={"status": "suspended"},
                           headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 409
    assert r.json()["code"] == "CANNOT_SUSPEND_SELF"


async def test_manager_suspends_staff_in_branch(client: AsyncClient, umctx: dict):
    uid = umctx["staff_a"]["id"]
    r = await client.patch(f"{USERS}/{uid}/status", json={"status": "suspended"},
                           headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 200, r.text


async def test_manager_cannot_suspend_other_branch(client: AsyncClient, umctx: dict):
    uid = umctx["staff_b"]["id"]
    r = await client.patch(f"{USERS}/{uid}/status", json={"status": "suspended"},
                           headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 403


async def test_manager_cannot_suspend_owner(client: AsyncClient, umctx: dict):
    uid = umctx["owner"]["user_id"]
    r = await client.patch(f"{USERS}/{uid}/status", json={"status": "suspended"},
                           headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 403


# ── staff không quản lý được ai ──────────────────────────────────────────────
async def test_staff_cannot_manage(client: AsyncClient, umctx: dict):
    uid = umctx["staff_b"]["id"]
    a = await client.post(f"{USERS}/{uid}/reset-password", json={"password": "x123456"},
                          headers=auth_headers(umctx["staff_token"]))
    assert a.status_code == 403
    b = await client.patch(f"{USERS}/{uid}/status", json={"status": "suspended"},
                           headers=auth_headers(umctx["staff_token"]))
    assert b.status_code == 403


# ── tài khoản theo ca (username) ─────────────────────────────────────────────
async def test_shift_account_username_login(client: AsyncClient, umctx: dict):
    r = await client.post(USERS, json={
        "full_name": "NV ca sáng - Trần Phú", "phone": "nv_ca_sang", "password": "sang123",
        "role": "staff", "branch_id": umctx["branch_a"]["id"],
    }, headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 201, r.text
    # đăng nhập bằng "username" theo ca.
    ok = await client.post("/api/v1/auth/login", json={"phone": "nv_ca_sang", "password": "sang123"})
    assert ok.status_code == 200


# ── list kèm branch_name + in_open_shift ─────────────────────────────────────
async def test_list_enriched_branch_and_open_shift(client: AsyncClient, umctx: dict):
    # staff A mở ca → in_open_shift = True cho staff A.
    op = await client.post("/api/v1/shifts/open", json={"opening_cash": 0},
                           headers=auth_headers(umctx["staff_token"]))
    assert op.status_code == 201, op.text

    r = await client.get(USERS, headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 200
    by_id = {u["id"]: u for u in r.json()["items"]}
    sa = by_id[umctx["staff_a"]["id"]]
    assert sa["in_open_shift"] is True
    assert sa["branch_name"] == "CN A"
    # staff B chưa mở ca.
    assert by_id[umctx["staff_b"]["id"]]["in_open_shift"] is False


async def test_manager_list_scope_only_own_branch(client: AsyncClient, umctx: dict):
    r = await client.get(USERS, headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 200
    branch_ids = {u["branch_id"] for u in r.json()["items"]}
    assert branch_ids == {umctx["branch_a"]["id"]}  # chỉ branch A


# ── sửa thông tin (update) + guard role owner ────────────────────────────────
# Bug gốc: guard chặn theo SỰ CÓ MẶT của role trong payload, không theo role THAY
# ĐỔI → FE luôn gửi role="owner" (không đổi) → đổi tên owner cũng bị chặn nhầm.
async def test_owner_edit_full_name_role_unchanged(client: AsyncClient, umctx: dict):
    """⭐ Case bug: sửa full_name owner, GỬI KÈM role='owner' (không đổi) → phải OK."""
    uid = umctx["owner"]["user_id"]
    r = await client.patch(f"{USERS}/{uid}", json={
        "full_name": "Chủ Tiệm Mới", "role": "owner",
    }, headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["full_name"] == "Chủ Tiệm Mới"
    assert r.json()["role"] == "owner"


async def test_owner_edit_own_phone(client: AsyncClient, umctx: dict):
    uid = umctx["owner"]["user_id"]
    r = await client.patch(f"{USERS}/{uid}", json={
        "phone": "0911111199", "role": "owner",
    }, headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["phone"] == "0911111199"


async def test_cannot_change_owner_role(client: AsyncClient, umctx: dict):
    """⭐ Đổi role owner THẬT (owner→staff) → vẫn 403 (bảo vệ owner cuối)."""
    uid = umctx["owner"]["user_id"]
    r = await client.patch(f"{USERS}/{uid}", json={"role": "staff"},
                           headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 403
    assert r.json()["code"] == "FORBIDDEN"


async def test_manager_cannot_escalate_role(client: AsyncClient, umctx: dict):
    """Manager nâng staff→manager (leo quyền) → vẫn 403."""
    uid = umctx["staff_a"]["id"]
    r = await client.patch(f"{USERS}/{uid}", json={"role": "manager"},
                           headers=auth_headers(umctx["manager_token"]))
    assert r.status_code == 403
    # và lên owner cũng cấm.
    r2 = await client.patch(f"{USERS}/{uid}", json={"role": "owner"},
                            headers=auth_headers(umctx["manager_token"]))
    assert r2.status_code == 403


async def test_owner_changes_staff_role_ok(client: AsyncClient, umctx: dict):
    """Đổi role nhân viên thường (staff→shipper) → OK."""
    uid = umctx["staff_a"]["id"]
    r = await client.patch(f"{USERS}/{uid}", json={
        "full_name": "NV đổi tên", "role": "shipper",
    }, headers=auth_headers(umctx["owner_token"]))
    assert r.status_code == 200, r.text
    assert r.json()["role"] == "shipper"
    assert r.json()["full_name"] == "NV đổi tên"


# ── tenant isolation ─────────────────────────────────────────────────────────
async def test_cross_tenant_manage_404(client: AsyncClient, umctx: dict, owner2: dict):
    t2 = await login(client, owner2["phone"], owner2["password"])
    uid = umctx["staff_a"]["id"]  # thuộc tenant 1
    r = await client.post(f"{USERS}/{uid}/reset-password", json={"password": "x123456"},
                          headers=auth_headers(t2))
    assert r.status_code == 404
    s = await client.patch(f"{USERS}/{uid}/status", json={"status": "suspended"},
                           headers=auth_headers(t2))
    assert s.status_code == 404
