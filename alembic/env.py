"""Alembic environment — async (asyncpg). Nạp URL & target_metadata từ app."""
import asyncio
import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy.ext.asyncio import async_engine_from_config
from sqlalchemy import pool

from app.core.config import get_settings
from app.core.database import Base

# Import models để Base.metadata thấy hết bảng (autogenerate).
from app import models  # noqa: F401,E402

config = context.config

# Connection MIGRATION tách khỏi app (RLS R1): ưu tiên MIGRATION_DATABASE_URL
# (user OWNER `laundry` — bypass RLS, sở hữu bảng → migrate không vướng policy);
# fallback DATABASE_URL khi chưa tách (app dùng `laundry_app` sau R1, bị RLS chặn).
# ⚠️ Test PHẢI override MIGRATION_DATABASE_URL về DB `_test` (xem conftest) — nếu không,
#    biến này (vd .env prod) sẽ khiến test migrate NHẦM vào DB prod.
migration_url = os.environ.get("MIGRATION_DATABASE_URL") or get_settings().database_url
config.set_main_option("sqlalchemy.url", migration_url)

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def run_migrations_offline() -> None:
    """Chạy migration ở chế độ offline (sinh SQL, không cần DBAPI)."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def do_run_migrations(connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_migrations_online() -> None:
    """Chạy migration ở chế độ online với async engine."""
    connectable = async_engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)
    await connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    asyncio.run(run_migrations_online())
