"""Mẫu in CHUẨN system-wide (Super Admin) — app_settings NGOÀI RLS + copy lúc tạo tenant.

⚠️ Chạy app_role_engine (laundry_app NON-BYPASS): app_settings ngoài RLS → GUC rỗng vẫn
đọc/ghi được; nếu lỡ bật RLS → chặn → bắt lỗi. create_tenant COPY mẫu vào receipt_config.
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SessionFactory, _AppSyncSession, get_db
from app.core.security import hash_password
from app.main import app
from app.models.admin import Admin
from tests.conftest import auth_headers

DEFAULT_RECEIPT = "/api/v1/admin/default-receipt"
TENANTS = "/api/v1/admin/tenants"
ADMIN_LOGIN = "/api/v1/admin/auth/login"
USER_LOGIN = "/api/v1/auth/login"
RECEIPT = "/api/v1/settings/receipt"


@pytest_asyncio.fixture
async def rls_db(app_role_engine):
    role_sm = async_sessionmaker(
        bind=app_role_engine, class_=AsyncSession,
        sync_session_class=_AppSyncSession, expire_on_commit=False,
    )

    async def _role_get_db():
        async with role_sm() as s:
            yield s

    app.dependency_overrides[get_db] = _role_get_db
    yield
    app.dependency_overrides.pop(get_db, None)


async def _seed_admin(phone: str) -> dict:
    async with SessionFactory() as db:
        db.add(Admin(
            phone=phone, full_name="SA", role="super_admin",
            password_hash=hash_password("admin-pw-123"), status="active",
        ))
        await db.commit()
    return {"phone": phone, "password": "admin-pw-123"}


async def _atok(client, admin) -> str:
    r = await client.post(ADMIN_LOGIN, json={"phone": admin["phone"], "password": admin["password"]})
    assert r.status_code == 200, r.text
    return r.json()["access_token"]


def _tpl(brand_vi="MẪU CHUẨN"):
    return {
        "bilingual": True,
        "track_base_url": "https://t.example/",
        "blocks": [
            {"id": "brand", "type": "custom_text", "enabled": True, "row": 0, "col": "full",
             "title": True, "content": {"vi": brand_vi}},
            {"id": "items_table", "type": "items_table", "enabled": True, "row": 1, "col": "full"},
        ],
    }


def _tpl_no_paystatus():
    """Mẫu default đã lưu TRƯỚC Bước 1: có 'totals', KHÔNG có payment_status."""
    return {
        "bilingual": True,
        "track_base_url": "https://t.example/",
        "blocks": [
            {"id": "items_table", "type": "items_table", "enabled": True, "row": 0, "col": "full"},
            {"id": "totals", "type": "totals", "enabled": True, "row": 1, "col": "full"},
            {"id": "footer", "type": "custom_text", "enabled": True, "row": 2, "col": "full",
             "content": {"vi": "Cảm ơn"}},
        ],
    }


# ── ⭐ app_settings đọc/ghi dưới RLS thật + GET fallback ──────────────────────
async def test_default_receipt_roundtrip_under_rls(client, rls_db):
    atok = await _atok(client, await _seed_admin("0996600001"))
    g0 = (await client.get(DEFAULT_RECEIPT, headers=auth_headers(atok))).json()
    assert g0["blocks"]  # chưa set → mẫu gốc nền tảng (placeholder)

    r = await client.put(DEFAULT_RECEIPT, json=_tpl("MY TEMPLATE"), headers=auth_headers(atok))
    assert r.status_code == 200, r.text
    g = (await client.get(DEFAULT_RECEIPT, headers=auth_headers(atok))).json()
    brand = next(b for b in g["blocks"] if b["id"] == "brand")
    assert brand["content"]["vi"] == "MY TEMPLATE"
    assert g["track_base_url"] == "https://t.example/"


async def test_put_strips_branch_contact_and_logo(client, rls_db):
    atok = await _atok(client, await _seed_admin("0996600002"))
    body = _tpl()
    body["logo_url"] = "https://evil/logo.png"
    body["branch_contact_blocks"] = {"some-branch": [{"id": "x", "type": "custom_text", "enabled": True}]}
    g = (await client.put(DEFAULT_RECEIPT, json=body, headers=auth_headers(atok))).json()
    assert g["logo_url"] == ""              # mẫu chuẩn không giữ logo
    assert g["branch_contact_blocks"] == {}  # không giữ liên hệ per-CN


# ── ⭐ create_tenant COPY mẫu chuẩn ──────────────────────────────────────────
async def test_create_tenant_copies_template(client, rls_db):
    atok = await _atok(client, await _seed_admin("0996600003"))
    await client.put(DEFAULT_RECEIPT, json=_tpl("COPIED"), headers=auth_headers(atok))

    r = await client.post(
        TENANTS,
        json={"name": "Shop X", "slug": "copy-x", "owner_full_name": "O",
              "owner_phone": "0905600001", "owner_password": "passw1"},
        headers=auth_headers(atok),
    )
    assert r.status_code == 201, r.text
    otok = (await client.post(USER_LOGIN, json={"phone": "0905600001", "password": "passw1", "slug": "copy-x"})).json()["access_token"]
    rc = (await client.get(RECEIPT, headers=auth_headers(otok))).json()
    assert any((b.get("content") or {}).get("vi") == "COPIED" for b in rc["blocks"])
    assert rc["track_base_url"] == "https://t.example/"


# ── ⭐ Fallback: chưa set mẫu → receipt_config NULL → _default_receipt() ──────
async def test_create_tenant_fallback_no_template(client, rls_db):
    atok = await _atok(client, await _seed_admin("0996600004"))
    r = await client.post(
        TENANTS,
        json={"name": "Shop Y", "slug": "fb-y", "owner_full_name": "O",
              "owner_phone": "0905600002", "owner_password": "passw1"},
        headers=auth_headers(atok),
    )
    assert r.status_code == 201, r.text  # tạo tenant KHÔNG gãy dù chưa set mẫu
    otok = (await client.post(USER_LOGIN, json={"phone": "0905600002", "password": "passw1", "slug": "fb-y"})).json()["access_token"]
    rc = (await client.get(RECEIPT, headers=auth_headers(otok))).json()
    # = _default_receipt(): có placeholder "[Tên tiệm]" của mẫu gốc nền tảng.
    assert any("[Tên tiệm]" in ((b.get("content") or {}).get("vi") or "") for b in rc["blocks"])
    # Stage default-trim: tenant NULL-config (fallback _default) KHÔNG có 2 khối đã bỏ.
    blob = str(rc["blocks"])
    assert "[Địa chỉ]" not in blob and "Cảm ơn quý khách" not in blob


# ── ⭐ MERGE-ON-READ: mẫu default lưu trước Bước 1 (thiếu payment_status) ──────
async def test_get_default_merges_payment_status_after_totals(client, rls_db):
    atok = await _atok(client, await _seed_admin("0996600005"))
    await client.put(DEFAULT_RECEIPT, json=_tpl_no_paystatus(), headers=auth_headers(atok))

    g = (await client.get(DEFAULT_RECEIPT, headers=auth_headers(atok))).json()
    blocks = sorted(g["blocks"], key=lambda b: b["row"])
    types = [b["type"] for b in blocks]
    assert types.count("payment_status") == 1
    assert types.index("payment_status") == types.index("totals") + 1  # ngay sau totals

    pb = next(b for b in blocks if b["type"] == "payment_status")
    assert pb["removable"] is False
    assert "Đã thanh toán" in pb["content"]["paid_vi"] and "Оплачено" in pb["content"]["paid_vi"]


async def test_get_default_merge_idempotent_and_persists(client, rls_db):
    atok = await _atok(client, await _seed_admin("0996600006"))
    await client.put(DEFAULT_RECEIPT, json=_tpl_no_paystatus(), headers=auth_headers(atok))

    g1 = (await client.get(DEFAULT_RECEIPT, headers=auth_headers(atok))).json()
    g2 = (await client.get(DEFAULT_RECEIPT, headers=auth_headers(atok))).json()
    assert sum(b["type"] == "payment_status" for b in g1["blocks"]) == 1
    assert sum(b["type"] == "payment_status" for b in g2["blocks"]) == 1  # GET lại không nhân đôi

    # Admin LƯU lại (đã merge) → stored có payment_status → GET sau merge no-op (vẫn 1).
    await client.put(DEFAULT_RECEIPT, json={
        "bilingual": g1["bilingual"], "track_base_url": g1["track_base_url"], "blocks": g1["blocks"],
    }, headers=auth_headers(atok))
    g3 = (await client.get(DEFAULT_RECEIPT, headers=auth_headers(atok))).json()
    assert sum(b["type"] == "payment_status" for b in g3["blocks"]) == 1


async def test_new_tenant_gets_payment_status(client, rls_db):
    atok = await _atok(client, await _seed_admin("0996600007"))
    await client.put(DEFAULT_RECEIPT, json=_tpl_no_paystatus(), headers=auth_headers(atok))

    r = await client.post(
        TENANTS,
        json={"name": "Shop Z", "slug": "ps-z", "owner_full_name": "O",
              "owner_phone": "0905600003", "owner_password": "passw1"},
        headers=auth_headers(atok),
    )
    assert r.status_code == 201, r.text
    otok = (await client.post(USER_LOGIN, json={"phone": "0905600003", "password": "passw1", "slug": "ps-z"})).json()["access_token"]
    rc = (await client.get(RECEIPT, headers=auth_headers(otok))).json()
    ps = [b for b in rc["blocks"] if b["type"] == "payment_status"]
    assert len(ps) == 1 and ps[0]["removable"] is False  # tenant MỚI có payment_status
