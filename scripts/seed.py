"""Seed dữ liệu dev: 1 tenant "Giặt Ủi 2H" + 1 user owner để test login.

Chạy: docker compose exec app sh -c "cd /code && python -m scripts.seed"
Idempotent: chạy lại không tạo trùng.
"""
import asyncio

from sqlalchemy import select

from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.service import Service, ServiceTier
from app.models.tenant import Tenant
from app.models.user import User

TENANT_SLUG = "giat-ui-2h"
OWNER_PHONE = "0900000001"
OWNER_PASSWORD = "owner123"  # dev only

# Bảng giá thật Giặt Ủi 2H: giặt sấy theo bậc cân; đồ lẻ owner tự thêm qua UI.
GIAT_SAY_NAME = "Giặt sấy"
GIAT_SAY_TIERS = [
    # (label, max_value, price, per_unit) — bậc cuối overflow >7kg tính 18k/kg.
    ("≤3kg", 3, 60000, False),
    ("5kg", 5, 90000, False),
    ("7kg", 7, 120000, False),
    (">7kg", None, 18000, True),
]


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

        # Bảng giá giặt sấy (idempotent: chỉ tạo nếu chưa có).
        giat_say = (
            await db.execute(
                select(Service).where(
                    Service.tenant_id == tenant.id, Service.name == GIAT_SAY_NAME
                )
            )
        ).scalar_one_or_none()
        if giat_say is None:
            service = Service(
                tenant_id=tenant.id,
                name=GIAT_SAY_NAME,
                unit="kg",
                pricing_type="tier",
                unit_price=0,
                display_order=1,
                is_active=True,
                tiers=[
                    ServiceTier(
                        label=label, max_value=max_value, price=price,
                        per_unit=per_unit, display_order=i,
                    )
                    for i, (label, max_value, price, per_unit) in enumerate(GIAT_SAY_TIERS)
                ],
            )
            db.add(service)
            print(f"[seed] created service '{GIAT_SAY_NAME}' ({len(GIAT_SAY_TIERS)} bậc giá)")
        else:
            print(f"[seed] service '{GIAT_SAY_NAME}' exists")

        await db.commit()


if __name__ == "__main__":
    asyncio.run(seed())
