"""Khôi phục mẫu in LOAD-ONLY — 2 GET read-only (Owner): mẫu của tôi + mẫu gốc hệ thống.

⚠️ Chạy app_role_engine (laundry_app NON-BYPASS): system-default đọc app_settings (NGOÀI RLS)
trong context tenant — GUC=tenant vẫn đọc được. Owner-only (staff 403). KHÔNG commit (load-only).
"""
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.database import SessionFactory, _AppSyncSession, get_db
from app.core.security import hash_password
from app.main import app
from app.models.app_settings import AppSettings
from app.models.tenant_settings import TenantSettings
from app.models.user import User
from tests.conftest import auth_headers, login

SYS = "/api/v1/settings/system-default-receipt"
MINE = "/api/v1/settings/receipt/my-default"
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


def _tpl(brand):
    return {
        "bilingual": True, "logo_url": "", "track_base_url": "https://sys.example/",
        "blocks": [{"id": "brand", "type": "custom_text", "enabled": True, "row": 0,
                    "col": "full", "content": {"vi": brand}}],
        "branch_contact_blocks": {},
    }


async def _set_system_default(value):
    async with SessionFactory() as db:
        row = await db.get(AppSettings, "default_receipt")
        if row is None:
            db.add(AppSettings(key="default_receipt", value=value))
        else:
            row.value = value
        await db.commit()


async def _set_tenant_default(tenant_id, value):
    async with SessionFactory() as db:
        s = await db.get(TenantSettings, tenant_id)
        if s is None:
            s = TenantSettings(tenant_id=tenant_id)
            db.add(s)
        s.receipt_default_config = value
        await db.commit()


async def _make_staff(tenant_id, phone="0900000099"):
    async with SessionFactory() as db:
        db.add(User(
            tenant_id=tenant_id, branch_id=None, role="staff", full_name="NV",
            phone=phone, password_hash=hash_password("staff123"), status="active",
        ))
        await db.commit()
    return phone


# ── ⭐ system-default dưới tenant Owner (app_settings NGOÀI RLS) ──────────────
async def test_system_default_set_and_fallback(client, owner, rls_db):
    tok = await login(client, owner["phone"], owner["password"])
    # CHƯA set → mẫu gốc nền tảng (_default_receipt placeholder "[Tên tiệm]")
    g0 = (await client.get(SYS, headers=auth_headers(tok))).json()
    assert any("[Tên tiệm]" in ((b.get("content") or {}).get("vi") or "") for b in g0["blocks"])
    # ĐÃ set → trả mẫu chuẩn Super Admin
    await _set_system_default(_tpl("MẪU HỆ THỐNG"))
    g = (await client.get(SYS, headers=auth_headers(tok))).json()
    assert any((b.get("content") or {}).get("vi") == "MẪU HỆ THỐNG" for b in g["blocks"])
    assert g["track_base_url"] == "https://sys.example/"


# ── my-default: có → trả; null → 404 NO_DEFAULT ──────────────────────────────
async def test_my_default_present_and_404(client, owner, rls_db):
    tok = await login(client, owner["phone"], owner["password"])
    r404 = await client.get(MINE, headers=auth_headers(tok))
    assert r404.status_code == 404 and r404.json()["code"] == "NO_DEFAULT"
    await _set_tenant_default(owner["tenant_id"], _tpl("MẪU CỦA TÔI"))
    g = (await client.get(MINE, headers=auth_headers(tok))).json()
    assert any((b.get("content") or {}).get("vi") == "MẪU CỦA TÔI" for b in g["blocks"])


# ── ⭐ Owner-only: staff → 403 cả 2 GET ──────────────────────────────────────
async def test_restore_endpoints_owner_only(client, owner, rls_db):
    staff_phone = await _make_staff(owner["tenant_id"])
    stok = await login(client, staff_phone, "staff123")
    rs = await client.get(SYS, headers=auth_headers(stok))
    rm = await client.get(MINE, headers=auth_headers(stok))
    assert rs.status_code == 403 and rs.json()["code"] == "FORBIDDEN"
    assert rm.status_code == 403 and rm.json()["code"] == "FORBIDDEN"


# ── ⭐ LOAD-ONLY: 2 GET KHÔNG commit → receipt_config bất biến ────────────────
async def test_loadonly_does_not_commit(client, owner, rls_db):
    tok = await login(client, owner["phone"], owner["password"])
    await _set_system_default(_tpl("HỆ THỐNG"))
    before = (await client.get(RECEIPT, headers=auth_headers(tok))).json()
    await client.get(SYS, headers=auth_headers(tok))                 # nạp mẫu hệ thống
    await _set_tenant_default(owner["tenant_id"], _tpl("CỦA TÔI"))
    await client.get(MINE, headers=auth_headers(tok))               # nạp mẫu của tôi
    after = (await client.get(RECEIPT, headers=auth_headers(tok))).json()
    assert before == after  # receipt_config KHÔNG đổi (read-only, không lưu)
