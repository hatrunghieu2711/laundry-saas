"""Engine & session factory — SQLAlchemy 2.0 async (asyncpg)."""
from collections.abc import AsyncGenerator

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session

from app.core.config import get_settings
from app.core.tenant_ctx import get_current_tenant


class Base(DeclarativeBase):
    """Base cho mọi ORM model (models viết ở Stage sau)."""


_settings = get_settings()

engine: AsyncEngine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
    pool_pre_ping=True,
)


class _AppSyncSession(Session):
    """Sync Session class RIÊNG của app — để gắn event after_begin (set GUC tenant
    cho RLS) CHỈ cho session của app, không đụng Session toàn cục / thư viện khác."""


SessionFactory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    sync_session_class=_AppSyncSession,
    expire_on_commit=False,
)


@event.listens_for(_AppSyncSession, "after_begin")
def _set_tenant_guc(session, transaction, connection) -> None:
    """RLS R2 — set tenant context vào DB cho MỖI transaction.

    ⚠️ `commit()` TRẢ connection về pool (đã đo) → set 1 lần không đủ. after_begin
    fire mỗi lần mở transaction (kể cả re-begin sau commit) → set lại từ ContextVar.
    is_local=true (transaction-scoped): tự xóa khi commit/rollback → connection trả
    pool SẠCH (chống leak), vẫn sống qua multi-commit nhờ re-apply mỗi txn. Bound
    param (:tid) chống injection. ContextVar rỗng (login/refresh) → GUC '' (không lỗi).
    Handler chạy trong greenlet của async driver; ContextVar được copy vào greenlet."""
    tid = get_current_tenant() or ""
    connection.execute(
        text("SELECT set_config('app.current_tenant_id', :tid, true)"),
        {"tid": tid},
    )


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: cấp một AsyncSession mỗi request."""
    async with SessionFactory() as session:
        yield session
