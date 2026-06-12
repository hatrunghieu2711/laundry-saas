"""Test auth flow: login, me, refresh rotation, logout."""
from httpx import AsyncClient

from tests.conftest import make_expired_access_token

LOGIN = "/api/v1/auth/login"
REFRESH = "/api/v1/auth/refresh"
LOGOUT = "/api/v1/auth/logout"
ME = "/api/v1/auth/me"
REFRESH_COOKIE = "refresh_token"
CSRF_COOKIE = "csrf_token"


def _set_cookies(client: AsyncClient, **cookies: str) -> None:
    """Đặt cookie trực tiếp lên client jar (tránh deprecation của per-request cookies)."""
    client.cookies.clear()
    for k, v in cookies.items():
        client.cookies.set(k, v)


async def _login(client: AsyncClient, owner: dict) -> dict:
    """Đăng nhập, trả access_token + refresh_raw + csrf."""
    resp = await client.post(LOGIN, json={"phone": owner["phone"], "password": owner["password"]})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    return {
        "access_token": body["access_token"],
        "csrf": body["csrf_token"],
        "refresh_raw": resp.cookies.get(REFRESH_COOKIE),
    }


# ── login ───────────────────────────────────────────────────────────────
async def test_login_success(client: AsyncClient, owner: dict):
    resp = await client.post(LOGIN, json={"phone": owner["phone"], "password": owner["password"]})
    assert resp.status_code == 200
    body = resp.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 1800
    assert body["access_token"]
    assert body["csrf_token"]
    # refresh token nằm trong cookie httpOnly, KHÔNG ở body.
    assert "refresh_token" not in body
    assert resp.cookies.get(REFRESH_COOKIE)


async def test_login_wrong_password(client: AsyncClient, owner: dict):
    resp = await client.post(LOGIN, json={"phone": owner["phone"], "password": "sai-mat-khau"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_unknown_phone(client: AsyncClient, owner: dict):
    resp = await client.post(LOGIN, json={"phone": "0000000000", "password": "owner123"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


# ── me ──────────────────────────────────────────────────────────────────
async def test_me_valid_token(client: AsyncClient, owner: dict):
    session = await _login(client, owner)
    resp = await client.get(ME, headers={"Authorization": f"Bearer {session['access_token']}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone"] == owner["phone"]
    assert body["role"] == "owner"
    assert body["tenant_id"] == str(owner["tenant_id"])
    assert body["branch_id"] is None


async def test_me_no_token(client: AsyncClient, owner: dict):
    resp = await client.get(ME)
    assert resp.status_code == 401
    assert resp.json()["code"] == "NOT_AUTHENTICATED"


async def test_me_expired_token(client: AsyncClient, owner: dict):
    expired = make_expired_access_token(owner["user_id"], owner["tenant_id"])
    resp = await client.get(ME, headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "TOKEN_EXPIRED"


# ── refresh rotation ──────────────────────────────────────────────────────
async def test_refresh_rotation(client: AsyncClient, owner: dict):
    s = await _login(client, owner)

    # Rotate: refresh cũ -> access + refresh mới.
    _set_cookies(client, **{REFRESH_COOKIE: s["refresh_raw"], CSRF_COOKIE: s["csrf"]})
    r1 = await client.post(REFRESH, headers={"X-CSRF-Token": s["csrf"]})
    assert r1.status_code == 200, r1.text
    new_refresh = r1.cookies.get(REFRESH_COOKIE)
    new_csrf = r1.json()["csrf_token"]
    assert new_refresh and new_refresh != s["refresh_raw"]

    # Refresh CŨ phải bị từ chối (đã revoke khi rotate).
    _set_cookies(client, **{REFRESH_COOKIE: s["refresh_raw"], CSRF_COOKIE: s["csrf"]})
    r_old = await client.post(REFRESH, headers={"X-CSRF-Token": s["csrf"]})
    assert r_old.status_code == 401
    assert r_old.json()["code"] == "INVALID_REFRESH_TOKEN"

    # Refresh MỚI vẫn dùng được.
    _set_cookies(client, **{REFRESH_COOKIE: new_refresh, CSRF_COOKIE: new_csrf})
    r_new = await client.post(REFRESH, headers={"X-CSRF-Token": new_csrf})
    assert r_new.status_code == 200


async def test_refresh_csrf_mismatch(client: AsyncClient, owner: dict):
    s = await _login(client, owner)
    _set_cookies(client, **{REFRESH_COOKIE: s["refresh_raw"], CSRF_COOKIE: s["csrf"]})
    resp = await client.post(REFRESH, headers={"X-CSRF-Token": "gia-mao"})
    assert resp.status_code == 403
    assert resp.json()["code"] == "CSRF_FAILED"


# ── logout ────────────────────────────────────────────────────────────────
async def test_logout_then_refresh_fails(client: AsyncClient, owner: dict):
    s = await _login(client, owner)

    _set_cookies(client, **{REFRESH_COOKIE: s["refresh_raw"], CSRF_COOKIE: s["csrf"]})
    logout = await client.post(LOGOUT)
    assert logout.status_code == 200

    # Sau logout, refresh token đã revoke -> refresh phải fail.
    _set_cookies(client, **{REFRESH_COOKIE: s["refresh_raw"], CSRF_COOKIE: s["csrf"]})
    resp = await client.post(REFRESH, headers={"X-CSRF-Token": s["csrf"]})
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_REFRESH_TOKEN"
