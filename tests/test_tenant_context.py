"""Test cơ chế tenant context per-request cho RLS (Stage R2) — CHƯA bật RLS.

Chỉ kiểm CƠ CHẾ GUC: set từ ContextVar, sống qua multi-commit (after_begin re-apply),
và QUAN TRỌNG NHẤT là KHÔNG LEAK giữa 2 request trên cùng pool. Cách ly RLS thật
(tenant A không đọc được data tenant B) sẽ test ở R3 sau khi có policy + role app.
"""
import pytest
from sqlalchemy import text

from app.core.database import SessionFactory
from app.core.tenant_ctx import reset_current_tenant, set_current_tenant

# missing_ok=true → trả '' nếu chưa set trong txn (không raise).
_GUC = "SELECT current_setting('app.current_tenant_id', true)"


async def _read_guc(s) -> str | None:
    return await s.scalar(text(_GUC))


async def test_contextvar_sets_guc():
    """ContextVar → after_begin set GUC đúng trong request."""
    set_current_tenant("tenant-A")
    try:
        async with SessionFactory() as s:
            assert await _read_guc(s) == "tenant-A"
    finally:
        reset_current_tenant()


async def test_guc_survives_multi_commit():
    """commit() trả connection về pool → after_begin phải re-apply mỗi txn.

    Kiểm 2 commit trong 1 request: GUC vẫn đúng sau mỗi commit."""
    set_current_tenant("tenant-A")
    try:
        async with SessionFactory() as s:
            v1 = await _read_guc(s)
            await s.commit()
            v2 = await _read_guc(s)  # txn MỚI → after_begin set lại từ ContextVar
            await s.commit()
            v3 = await _read_guc(s)
            assert v1 == v2 == v3 == "tenant-A"
    finally:
        reset_current_tenant()


async def test_no_leak_between_requests():
    """⭐ QUAN TRỌNG NHẤT: request sau (không tenant) KHÔNG thấy tenant của request trước.

    is_local=true → GUC tự xóa khi txn của request A kết thúc → connection trả pool
    SẠCH. Request B dùng lại connection đó vẫn thấy '' (không leak 'tenant-A')."""
    # request A: tenant-A
    set_current_tenant("tenant-A")
    try:
        async with SessionFactory() as s:
            assert await _read_guc(s) == "tenant-A"
    finally:
        reset_current_tenant()
    # request B: KHÔNG set tenant (vd login/refresh) — dùng lại pool
    async with SessionFactory() as s:
        leaked = await _read_guc(s)
        assert leaked in ("", None), f"LEAK: request sau thấy tenant {leaked!r}"


async def test_two_tenants_consecutive_isolated():
    """2 request khác tenant liên tiếp → mỗi cái thấy ĐÚNG tenant của mình."""
    for tid in ("tenant-A", "tenant-B"):
        set_current_tenant(tid)
        try:
            async with SessionFactory() as s:
                assert await _read_guc(s) == tid
        finally:
            reset_current_tenant()


async def test_empty_context_no_error():
    """ContextVar rỗng (login/refresh/public) → GUC rỗng, query vẫn chạy, không lỗi."""
    reset_current_tenant()
    async with SessionFactory() as s:
        assert await _read_guc(s) in ("", None)
        assert await s.scalar(text("SELECT 1")) == 1


async def test_guc_bound_param_no_injection():
    """set_config dùng BOUND PARAM → giá trị độc hại lưu nguyên văn, KHÔNG thực thi."""
    evil = "x'; SELECT 1; --"
    set_current_tenant(evil)
    try:
        async with SessionFactory() as s:
            assert await _read_guc(s) == evil
    finally:
        reset_current_tenant()


# ── Sequence Cách B: function SECURITY DEFINER (regex per-tenant) ────────────
# Tên sequence mới kèm tenant_id hex: order_code_seq_{32 hex}_b{n}.
_SEQ_NEW = "order_code_seq_" + "0" * 32 + "_b1"


async def test_app_create_order_seq_creates_and_nextval():
    """Tạo sequence qua function + nextval sinh mã đơn (path branch_service mới)."""
    async with SessionFactory() as s:
        await s.execute(text("SELECT app_create_order_seq(:n)"), {"n": _SEQ_NEW})
        await s.commit()
        assert await s.scalar(text(f"SELECT nextval('{_SEQ_NEW}')")) == 1


async def test_app_create_order_seq_rejects_bad_name():
    """Function validate tên (chống injection + chặn tên CŨ thiếu tenant_id) → RAISE."""
    async with SessionFactory() as s:
        with pytest.raises(Exception):
            await s.execute(
                text("SELECT app_create_order_seq(:n)"), {"n": "evil; DROP TABLE x"}
            )
    # Tên CŨ (order_code_seq_b1) nay cũng bị regex mới chặn.
    async with SessionFactory() as s:
        with pytest.raises(Exception):
            await s.execute(
                text("SELECT app_create_order_seq(:n)"), {"n": "order_code_seq_b1"}
            )
