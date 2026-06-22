"""Test auth flow: login, me, refresh rotation, logout."""
from httpx import AsyncClient

from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User
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


# ── login đa tenant: mã cửa hàng (slug) làm tenant context (Stage 6.76) ──────
async def _make_dup_phone_tenants() -> tuple[str, str, dict[str, object]]:
    """2 tenant khác nhau, CÙNG phone + CÙNG password — mô phỏng nhập nhằng đa tenant."""
    phone, password = "0988888888", "samepass123"
    ids: dict[str, object] = {}
    async with SessionFactory() as db:
        for name, slug in [("Tiệm A", "tiem-a"), ("Tiệm B", "tiem-b")]:
            tenant = Tenant(name=name, slug=slug, status="active")
            db.add(tenant)
            await db.flush()
            db.add(
                User(
                    tenant_id=tenant.id, branch_id=None, role="owner",
                    full_name=f"Chủ {name}", phone=phone,
                    password_hash=hash_password(password), status="active",
                )
            )
            ids[slug] = tenant.id
        await db.commit()
    return phone, password, ids


async def _tenant_of(client: AsyncClient, access_token: str) -> str:
    resp = await client.get(ME, headers={"Authorization": f"Bearer {access_token}"})
    assert resp.status_code == 200, resp.text
    return resp.json()["tenant_id"]


async def test_login_with_correct_slug(client: AsyncClient, owner: dict):
    resp = await client.post(
        LOGIN,
        json={"phone": owner["phone"], "password": owner["password"], "slug": "giat-ui-2h"},
    )
    assert resp.status_code == 200, resp.text
    assert await _tenant_of(client, resp.json()["access_token"]) == str(owner["tenant_id"])


async def test_login_without_slug_backward_compat(client: AsyncClient, owner: dict):
    """Giai đoạn 1: 2H login KHÔNG nhập mã vẫn được (backward-compat)."""
    resp = await client.post(LOGIN, json={"phone": owner["phone"], "password": owner["password"]})
    assert resp.status_code == 200, resp.text


async def test_login_empty_slug_treated_as_none(client: AsyncClient, owner: dict):
    """slug rỗng/space → coi như không nhập (tìm toàn cục) → vẫn login được."""
    resp = await client.post(
        LOGIN, json={"phone": owner["phone"], "password": owner["password"], "slug": "   "}
    )
    assert resp.status_code == 200, resp.text


async def test_login_unknown_slug_generic_401(client: AsyncClient, owner: dict):
    """slug không tồn tại → 401 generic (KHÔNG lộ 'tenant không tồn tại')."""
    resp = await client.post(
        LOGIN,
        json={"phone": owner["phone"], "password": owner["password"], "slug": "khong-co-tiem"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_slug_normalized_case_space(client: AsyncClient, owner: dict):
    """Mã có HOA + khoảng trắng → chuẩn hóa lowercase+trim khớp 'giat-ui-2h'."""
    resp = await client.post(
        LOGIN,
        json={"phone": owner["phone"], "password": owner["password"], "slug": "  GIAT-UI-2H "},
    )
    assert resp.status_code == 200, resp.text
    assert await _tenant_of(client, resp.json()["access_token"]) == str(owner["tenant_id"])


async def test_login_right_phone_wrong_tenant_slug(
    client: AsyncClient, owner: dict, owner2: dict
):
    """phone của 2H + slug của tenant KHÁC → 401 (phone không thuộc tenant đó)."""
    resp = await client.post(
        LOGIN,
        json={"phone": owner["phone"], "password": owner["password"], "slug": "sach-thom"},
    )
    assert resp.status_code == 401
    assert resp.json()["code"] == "INVALID_CREDENTIALS"


async def test_login_dup_phone_slug_matches_right_tenant(client: AsyncClient):
    """2 tenant trùng phone+pass: CÓ slug → match ĐÚNG tenant theo slug."""
    phone, password, ids = await _make_dup_phone_tenants()
    for slug in ("tiem-a", "tiem-b"):
        resp = await client.post(LOGIN, json={"phone": phone, "password": password, "slug": slug})
        assert resp.status_code == 200, resp.text
        assert await _tenant_of(client, resp.json()["access_token"]) == str(ids[slug])


async def test_login_dup_phone_no_slug_still_authenticates(client: AsyncClient):
    """2 tenant trùng phone+pass: KHÔNG slug → vẫn login (lấy ứng viên đầu — siết ở GĐ 2)."""
    phone, password, _ = await _make_dup_phone_tenants()
    resp = await client.post(LOGIN, json={"phone": phone, "password": password})
    assert resp.status_code == 200, resp.text


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


async def test_me_includes_tenant_name(client: AsyncClient, owner: dict):
    """⭐ /auth/me trả TÊN TIỆM (tenant.name) cho FE hiển thị menu/topbar."""
    session = await _login(client, owner)
    resp = await client.get(ME, headers={"Authorization": f"Bearer {session['access_token']}"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["tenant_name"] == "Giặt Ủi 2H"  # owner fixture tạo tenant tên này
    # tách bạch: tên TIỆM khác tên NGƯỜI.
    assert body["full_name"] == "Chủ Giặt Ủi 2H"


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


# ── change password (self-service) ─────────────────────────────────────────
CHANGE_PW = "/api/v1/auth/change-password"


def _bearer(session: dict) -> dict:
    return {"Authorization": f"Bearer {session['access_token']}"}


async def test_change_password_success(client: AsyncClient, owner: dict):
    s = await _login(client, owner)
    resp = await client.post(
        CHANGE_PW,
        json={"current_password": owner["password"], "new_password": "newpass123"},
        headers=_bearer(s),
    )
    assert resp.status_code == 200, resp.text
    # login bằng MK MỚI → OK
    r_new = await client.post(LOGIN, json={"phone": owner["phone"], "password": "newpass123"})
    assert r_new.status_code == 200
    # login bằng MK CŨ → thất bại (hash đã đổi)
    r_old = await client.post(LOGIN, json={"phone": owner["phone"], "password": owner["password"]})
    assert r_old.status_code == 401


async def test_change_password_wrong_current(client: AsyncClient, owner: dict):
    s = await _login(client, owner)
    resp = await client.post(
        CHANGE_PW,
        json={"current_password": "sai-mat-khau", "new_password": "newpass123"},
        headers=_bearer(s),
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "INVALID_CURRENT_PASSWORD"
    # MK KHÔNG đổi → login MK cũ vẫn được
    r_old = await client.post(LOGIN, json={"phone": owner["phone"], "password": owner["password"]})
    assert r_old.status_code == 200


async def test_change_password_too_short(client: AsyncClient, owner: dict):
    s = await _login(client, owner)
    resp = await client.post(
        CHANGE_PW,
        json={"current_password": owner["password"], "new_password": "123"},
        headers=_bearer(s),
    )
    assert resp.status_code == 422  # Pydantic min_length=6


async def test_change_password_requires_auth(client: AsyncClient, owner: dict):
    resp = await client.post(
        CHANGE_PW, json={"current_password": "x", "new_password": "newpass123"}
    )
    assert resp.status_code == 401


async def test_change_password_revokes_other_sessions_keeps_current(
    client: AsyncClient, owner: dict
):
    """Đổi MK từ device 1 → device 2 (thiết bị khác) bị đăng xuất; device 1 giữ phiên."""
    s1 = await _login(client, owner)  # phiên HIỆN TẠI (đổi MK ở đây)
    s2 = await _login(client, owner)  # thiết bị KHÁC

    # Đổi MK từ device 1: gửi access token + refresh cookie của device 1.
    _set_cookies(client, **{REFRESH_COOKIE: s1["refresh_raw"], CSRF_COOKIE: s1["csrf"]})
    resp = await client.post(
        CHANGE_PW,
        json={"current_password": owner["password"], "new_password": "newpass123"},
        headers=_bearer(s1),
    )
    assert resp.status_code == 200, resp.text

    # device 2 refresh → bị revoke (đăng xuất thiết bị khác)
    _set_cookies(client, **{REFRESH_COOKIE: s2["refresh_raw"], CSRF_COOKIE: s2["csrf"]})
    r2 = await client.post(REFRESH, headers={"X-CSRF-Token": s2["csrf"]})
    assert r2.status_code == 401
    assert r2.json()["code"] == "INVALID_REFRESH_TOKEN"

    # device 1 (phiên hiện tại) refresh → VẪN dùng được
    _set_cookies(client, **{REFRESH_COOKIE: s1["refresh_raw"], CSRF_COOKIE: s1["csrf"]})
    r1 = await client.post(REFRESH, headers={"X-CSRF-Token": s1["csrf"]})
    assert r1.status_code == 200


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
