"""Seed dữ liệu dev: 1 tenant "Giặt Ủi 2H" + 1 user owner để test login.

Chạy: docker compose exec app sh -c "cd /code && python -m scripts.seed"
Idempotent: chạy lại không tạo trùng.
"""
import asyncio

from sqlalchemy import select

from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.tenant import Tenant
from app.models.user import User

TENANT_SLUG = "giat-ui-2h"
OWNER_PHONE = "0900000001"
OWNER_PASSWORD = "owner123"  # dev only


async def seed() -> None:
    async with SessionFactory() as db:
        tenant = (
            await db.execute(select(Tenant).where(Tenant.slug == TENANT_SLUG))
        ).scalar_one_or_none()
        if tenant is None:
            tenant = Tenant(name="Giặt Ủi 2H", slug=TENANT_SLUG, status="active")
            db.add(tenant)
            await db.flush()
            print(f"[seed] created tenant {tenant.id} ({tenant.name})")
        else:
            print(f"[seed] tenant exists {tenant.id} ({tenant.name})")

        owner = (
            await db.execute(
                select(User).where(
                    User.tenant_id == tenant.id, User.phone == OWNER_PHONE
                )
            )
        ).scalar_one_or_none()
        if owner is None:
            owner = User(
                tenant_id=tenant.id,
                branch_id=None,
                role="owner",
                full_name="Chủ Giặt Ủi 2H",
                phone=OWNER_PHONE,
                password_hash=hash_password(OWNER_PASSWORD),
                status="active",
            )
            db.add(owner)
            print(f"[seed] created owner phone={OWNER_PHONE} password={OWNER_PASSWORD}")
        else:
            print(f"[seed] owner exists phone={OWNER_PHONE}")

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
