"""Test MIGRATION categories giữ nguyên dữ liệu cũ (Stage 4.3).

Kịch bản: ở revision TRƯỚC khi tách categories, services có cột text `category`.
Migration phải: tạo categories từ các giá trị text DISTINCT (gom trùng theo tenant),
map services.category_id tương ứng, services category NULL giữ category_id NULL —
KHÔNG mất dữ liệu.

Chạy trên một DB scratch riêng (tên '_test') để không đụng DB test chính: dựng
schema tới revision trước, chèn dữ liệu kiểu cũ, rồi `alembic upgrade head`.
"""
import os
import subprocess
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import create_async_engine

from tests.conftest import _PROJECT_ROOT, _TEST_URL

# Revision NGAY TRƯỚC migration categories (cash_transactions). Ở đây services
# vẫn còn cột text `category`.
PREV_REV = "a4b5c6d7e8f9"
SCRATCH_DB = "laundry_mig_test"  # kết thúc '_test' → an toàn


def _scratch_url() -> str:
    return make_url(_TEST_URL).set(database=SCRATCH_DB).render_as_string(hide_password=False)


async def _admin_exec(sql: str) -> None:
    admin = create_async_engine(
        make_url(_TEST_URL).set(database="postgres"), isolation_level="AUTOCOMMIT"
    )
    try:
        async with admin.connect() as conn:
            await conn.execute(text(sql))
    finally:
        await admin.dispose()


def _alembic_to(rev: str, url: str) -> None:
    env = os.environ.copy()
    env["DATABASE_URL"] = url
    subprocess.run(
        ["alembic", "upgrade", rev], check=True, cwd=_PROJECT_ROOT, env=env
    )


@pytest.mark.asyncio
async def test_migration_backfills_categories_preserving_data():
    await _admin_exec(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
    await _admin_exec(f'CREATE DATABASE "{SCRATCH_DB}"')
    scratch = _scratch_url()
    tid = uuid.uuid4()

    try:
        # 1) Dựng schema tới revision TRƯỚC (services còn cột text `category`).
        _alembic_to(PREV_REV, scratch)

        # 2) Chèn dữ liệu kiểu cũ: 2 dịch vụ "Giặt sấy", 1 "Đồ lẻ", 1 NULL.
        eng = create_async_engine(scratch)
        try:
            async with eng.begin() as conn:
                await conn.execute(
                    text("INSERT INTO tenants (id, name, slug, status) "
                         "VALUES (:id, 'Mig Tenant', 'mig-tenant', 'active')"),
                    {"id": tid},
                )
                rows = [
                    ("Giặt sấy A", "Giặt sấy", 1),
                    ("Giặt sấy B", "Giặt sấy", 1),
                    ("Áo Vest", "Đồ lẻ", 2),
                    ("Khăn lẻ", None, 3),
                ]
                for name, cat, order in rows:
                    await conn.execute(
                        text("INSERT INTO services "
                             "(id, tenant_id, name, unit, pricing_type, display_order, category) "
                             "VALUES (:id, :tid, :name, 'cai', 'per_unit', :ord, :cat)"),
                        {"id": uuid.uuid4(), "tid": tid, "name": name,
                         "ord": order, "cat": cat},
                    )
        finally:
            await eng.dispose()

        # 3) Áp migration categories (backfill chạy trong đây).
        _alembic_to("head", scratch)

        # 4) Kiểm chứng: không mất dữ liệu.
        eng = create_async_engine(scratch)
        try:
            async with eng.connect() as conn:
                # Cột text `category` đã bị bỏ.
                has_col = await conn.scalar(text(
                    "SELECT 1 FROM information_schema.columns "
                    "WHERE table_name='services' AND column_name='category'"
                ))
                assert has_col is None, "Cột text services.category phải bị drop sau migration"

                # Đúng 2 category (gom 'Giặt sấy' trùng thành 1), thứ tự theo display_order.
                cats = (await conn.execute(text(
                    "SELECT name, display_order FROM categories "
                    "WHERE tenant_id=:t ORDER BY display_order"
                ), {"t": tid})).all()
                assert [c[0] for c in cats] == ["Giặt sấy", "Đồ lẻ"]
                assert [c[1] for c in cats] == [0, 1]

                # Mỗi service map đúng category_id (hoặc NULL).
                rows = (await conn.execute(text(
                    "SELECT s.name, c.name FROM services s "
                    "LEFT JOIN categories c ON c.id = s.category_id "
                    "WHERE s.tenant_id=:t ORDER BY s.name"
                ), {"t": tid})).all()
                mapping = {r[0]: r[1] for r in rows}
                assert mapping["Giặt sấy A"] == "Giặt sấy"
                assert mapping["Giặt sấy B"] == "Giặt sấy"
                assert mapping["Áo Vest"] == "Đồ lẻ"
                assert mapping["Khăn lẻ"] is None
        finally:
            await eng.dispose()
    finally:
        await _admin_exec(f'DROP DATABASE IF EXISTS "{SCRATCH_DB}" WITH (FORCE)')
