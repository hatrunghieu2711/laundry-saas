"""Panel 'Thông tin tiệm' — /auth/me thêm field cho owner.

plan_name + branch_max (= effective_max) từ subscription_info; branch_count = số CN active
(1 count query); support_contact/support_zalo từ config. Field cũ GIỮ NGUYÊN.
"""
from httpx import AsyncClient

from app.core.config import get_settings
from tests.conftest import auth_headers, login

ME = "/api/v1/auth/me"
BRANCHES = "/api/v1/branches"


async def test_me_returns_tenant_info_fields(client: AsyncClient, owner: dict):
    """Owner /me: plan_name + branch_max + branch_count + support_contact đúng."""
    tok = await login(client, owner["phone"], owner["password"])
    # tạo 2 CN active (owner fixture custom_max=99 → không vướng giới hạn).
    for name in ("CN A", "CN B"):
        r = await client.post(BRANCHES, json={"name": name}, headers=auth_headers(tok))
        assert r.status_code == 201, r.text

    me = (await client.get(ME, headers=auth_headers(tok))).json()
    assert me["plan_name"] is not None              # gói từ seed
    assert me["branch_max"] == 99                    # custom_max fixture
    assert me["branch_count"] == 2                   # 2 CN active vừa tạo
    assert me["support_contact"] == get_settings().support_contact
    assert "support_zalo" in me


async def test_me_branch_count_excludes_soft_deleted(client: AsyncClient, owner: dict):
    """branch_count chỉ đếm CN ACTIVE — xóa (soft-delete) 1 CN → count giảm."""
    tok = await login(client, owner["phone"], owner["password"])
    ids = []
    for name in ("CN A", "CN B"):
        r = await client.post(BRANCHES, json={"name": name}, headers=auth_headers(tok))
        ids.append(r.json()["id"])
    assert (await client.get(ME, headers=auth_headers(tok))).json()["branch_count"] == 2

    rdel = await client.delete(f"{BRANCHES}/{ids[0]}", headers=auth_headers(tok))
    assert rdel.status_code == 200, rdel.text
    assert (await client.get(ME, headers=auth_headers(tok))).json()["branch_count"] == 1


async def test_me_keeps_existing_fields(client: AsyncClient, owner: dict):
    """Field cũ + expiry (stage trước) KHÔNG đổi (regression)."""
    tok = await login(client, owner["phone"], owner["password"])
    me = (await client.get(ME, headers=auth_headers(tok))).json()
    assert me["role"] == "owner"
    assert me["tenant_name"] and me["tenant_slug"]
    assert me["subscription_status"] == "active"     # NULL hạn = vô hạn
    assert me["subscription_expires_at"] is None
