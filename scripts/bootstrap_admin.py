"""Bootstrap admin #1 (Super Admin) — chưa có admin nào để tạo admin qua API.

Chạy: docker compose exec app sh -c "cd /code && python -m scripts.bootstrap_admin"

Nguồn thông tin (ưu tiên ENV, fallback nhập tay — KHÔNG hardcode password):
- SUPERADMIN_PHONE   : ENV hoặc input().
- SUPERADMIN_PASSWORD: ENV hoặc getpass(); để TRỐNG → sinh ngẫu nhiên + in ra 1 lần.
- SUPERADMIN_NAME    : ENV (mặc định "Super Admin").

Idempotent: đã có admin theo phone → bỏ qua, không tạo trùng.
"""
import asyncio
import getpass
import os
import secrets

from sqlalchemy import select

from app.core.database import SessionFactory
from app.core.security import hash_password
from app.models.admin import Admin


def _resolve_phone() -> str:
    phone = (os.environ.get("SUPERADMIN_PHONE") or input("Admin phone: ")).strip()
    if not phone:
        raise SystemExit("[bootstrap_admin] phone rỗng — hủy")
    return phone


def _resolve_password() -> tuple[str, bool]:
    """Trả (password, generated?). ENV > getpass > sinh ngẫu nhiên (in 1 lần)."""
    pw = os.environ.get("SUPERADMIN_PASSWORD")
    if pw:
        return pw, False
    pw = getpass.getpass("Admin password (Enter để sinh ngẫu nhiên): ")
    if pw:
        return pw, False
    return secrets.token_urlsafe(16), True


async def bootstrap() -> None:
    phone = _resolve_phone()
    full_name = os.environ.get("SUPERADMIN_NAME", "Super Admin")

    async with SessionFactory() as db:
        existing = (
            await db.execute(select(Admin).where(Admin.phone == phone))
        ).scalar_one_or_none()
        if existing is not None:
            print(f"[bootstrap_admin] admin phone={phone} đã tồn tại — bỏ qua (idempotent)")
            return

        password, generated = _resolve_password()
        db.add(
            Admin(
                phone=phone,
                full_name=full_name,
                role="super_admin",
                password_hash=hash_password(password),
                status="active",
            )
        )
        await db.commit()
        print(f"[bootstrap_admin] ĐÃ TẠO super_admin phone={phone} name='{full_name}'")
        if generated:
            print(f"[bootstrap_admin] ⚠️ MẬT KHẨU SINH NGẪU NHIÊN (LƯU LẠI NGAY): {password}")


if __name__ == "__main__":
    asyncio.run(bootstrap())
