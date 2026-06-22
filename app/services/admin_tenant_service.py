"""Admin tạo tenant mới — tiệm + CN đầu (B1) + owner + settings trong 1 TRANSACTION.

⚠️ ĐIỂM SỐNG CÒN:
- ATOMIC: 1 commit cuối; lỗi bất kỳ → rollback → KHÔNG để tenant "nửa vời".
- XUYÊN RLS: admin GUC rỗng. tenants NGOÀI RLS (insert OK), nhưng branch/user/settings
  STRICT RLS cần GUC = tenant_id mới. after_begin đã set GUC='' lúc get_current_admin
  load admin (cùng transaction) → đổi ContextVar giữa chừng KHÔNG cập nhật GUC. Phải
  set_config TƯỜNG MINH (is_local=true) cho txn đang mở → thỏa policy WITH CHECK,
  KHÔNG bypass RLS, KHÔNG dùng owner-engine.
- KHÔNG tái dùng create_branch/create_user/get_or_create (chúng commit RIÊNG → vỡ atomic).
"""
import secrets
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone

from sqlalchemy import func, select, text, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.security import hash_password
from app.models.branch import Branch
from app.models.order import Order
from app.models.refresh_token import RefreshToken
from app.models.tenant import Tenant
from app.models.tenant_settings import TenantSettings
from app.models.user import User
from app.schemas.admin import TenantAdminUpdate, TenantCreate
from app.services import tenant_service

# CN đầu của tenant mới: code/order_prefix = "B1" (theo convention branch_service).
_FIRST_BRANCH_CODE = "B1"
_SET_GUC = "SELECT set_config('app.current_tenant_id', :tid, true)"


@dataclass
class CreatedTenant:
    tenant_id: uuid.UUID
    slug: str
    owner_phone: str
    temp_password: str
    branch_code: str


def _seq_name(tenant_id: uuid.UUID, code: str) -> str:
    """Tên sequence order_code PER-TENANT (kèm tenant_id hex) — mỗi tenant đếm riêng."""
    return f"order_code_seq_{uuid.UUID(str(tenant_id)).hex}_{code.lower()}"


async def create_tenant(db: AsyncSession, data: TenantCreate) -> CreatedTenant:
    """Tạo tenant hoàn chỉnh trong 1 transaction. Trả slug + phone owner + mật khẩu tạm."""
    # a. Pre-check slug unique (chuẩn hóa lowercase+trim trong get_tenant_by_slug).
    if await tenant_service.get_tenant_by_slug(db, data.slug) is not None:
        raise APIError(409, "SLUG_EXISTS", "Mã cửa hàng (slug) đã tồn tại")

    # Mật khẩu owner: dùng cái admin truyền; thiếu → sinh ngẫu nhiên (hiện 1 lần).
    temp_password = data.owner_password or secrets.token_urlsafe(12)

    try:
        # b. Tenant (NGOÀI RLS → insert OK dù GUC rỗng). flush để lấy tenant.id.
        tenant = Tenant(name=data.name, slug=data.slug, status="active")
        db.add(tenant)
        await db.flush()

        # c. ⚠️ set GUC tường minh cho txn ĐANG MỞ (is_local=true → áp ngay, tự xóa
        # khi commit). BẮT BUỘC để insert bảng con strict RLS qua được WITH CHECK.
        await db.execute(text(_SET_GUC), {"tid": str(tenant.id)})

        # d. CN đầu B1 + sequence order_code (như branch_service: thiếu sequence →
        # tạo đơn sau 500). app_create_order_seq = SECURITY DEFINER (owner) nên role
        # app non-owner gọi được; CREATE SEQUENCE transactional → rollback theo txn.
        branch = Branch(
            tenant_id=tenant.id,
            name=data.branch_name,
            address=data.branch_address,
            phone=data.branch_phone,
            code=_FIRST_BRANCH_CODE,
            order_prefix=_FIRST_BRANCH_CODE,
            status="active",
        )
        db.add(branch)
        await db.flush()
        await db.execute(
            text("SELECT app_create_order_seq(:n)"),
            {"n": _seq_name(tenant.id, _FIRST_BRANCH_CODE)},
        )

        # e. Owner đầu (role=owner, branch_id=None → quản mọi CN). pw đã hash.
        db.add(
            User(
                tenant_id=tenant.id,
                branch_id=None,
                role="owner",
                full_name=data.owner_full_name,
                phone=data.owner_phone,
                email=None,
                password_hash=hash_password(temp_password),
                status="active",
            )
        )

        # f. Settings rỗng (server_default lo hết; receipt_config NULL → mẫu gốc nền tảng).
        db.add(TenantSettings(tenant_id=tenant.id))

        # g. MỘT commit cuối → atomic.
        await db.commit()
    except IntegrityError as exc:
        # slug/phone trùng (race vượt pre-check) → rollback sạch, không tenant mồ côi.
        await db.rollback()
        raise APIError(
            409, "TENANT_CREATE_CONFLICT", "Mã cửa hàng hoặc số điện thoại đã tồn tại"
        ) from exc

    return CreatedTenant(
        tenant_id=tenant.id,
        slug=tenant.slug,
        owner_phone=data.owner_phone,
        temp_password=temp_password,
        branch_code=_FIRST_BRANCH_CODE,
    )


# ── A3: list / detail / sửa / khóa / reset MK owner ─────────────────────────
@dataclass
class TenantStats:
    id: uuid.UUID
    name: str
    slug: str
    status: str
    created_at: datetime
    n_branches: int
    n_users: int
    last_order_at: datetime | None


async def _stats_for(db: AsyncSession, tenant: Tenant) -> TenantStats:
    """Đếm số liệu 1 tenant. ⚠️ set GUC = tenant TRƯỚC khi đếm bảng strict
    (branches/orders) — thiếu set_config thì RLS trả 0 (admin GUC rỗng). users
    permissive-when-empty (đếm WHERE tenant_id vẫn đúng). Lọc thêm tenant_id để
    đúng cả khi chạy bằng role owner-bypass (test harness)."""
    await db.execute(text(_SET_GUC), {"tid": str(tenant.id)})
    n_branches = await db.scalar(
        select(func.count()).select_from(Branch).where(Branch.tenant_id == tenant.id)
    )
    n_users = await db.scalar(
        select(func.count()).select_from(User).where(User.tenant_id == tenant.id)
    )
    last_order_at = await db.scalar(
        select(func.max(Order.created_at)).where(Order.tenant_id == tenant.id)
    )
    return TenantStats(
        id=tenant.id, name=tenant.name, slug=tenant.slug, status=tenant.status,
        created_at=tenant.created_at, n_branches=n_branches or 0, n_users=n_users or 0,
        last_order_at=last_order_at,
    )


async def list_tenants_with_stats(db: AsyncSession) -> list[TenantStats]:
    """List tenant (NGOÀI RLS) + số liệu mỗi tenant qua set_config loop (A2 pattern,
    KHÔNG bypass RLS). Chi phí N round-trip — chấp nhận khi ít tenant."""
    tenants = (
        await db.execute(select(Tenant).order_by(Tenant.created_at))
    ).scalars().all()
    out = [await _stats_for(db, t) for t in tenants]
    await db.execute(text(_SET_GUC), {"tid": ""})  # reset GUC sau loop (hygiene)
    return out


async def get_tenant_detail(db: AsyncSession, tenant_id: uuid.UUID) -> TenantStats:
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise APIError(404, "TENANT_NOT_FOUND", "Không tìm thấy cửa hàng")
    stats = await _stats_for(db, tenant)
    await db.execute(text(_SET_GUC), {"tid": ""})
    return stats


async def _revoke_tenant_refresh(db: AsyncSession, tenant_id: uuid.UUID) -> None:
    """Revoke MỌI refresh token còn hiệu lực của user thuộc tenant — để KHÓA thực sự
    hiệu lực (rotate_session KHÔNG check tenant.status). refresh_tokens NGOÀI RLS +
    users permissive-when-empty → KHÔNG cần GUC."""
    user_ids = select(User.id).where(User.tenant_id == tenant_id)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id.in_(user_ids), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )


async def _set_status(db: AsyncSession, tenant: Tenant, new_status: str) -> None:
    """Đổi status tenant. Khóa (status != active) → revoke refresh (chống khóa giả)."""
    tenant.status = new_status
    if new_status != "active":
        await _revoke_tenant_refresh(db, tenant.id)


async def update_tenant_admin(
    db: AsyncSession, tenant_id: uuid.UUID, data: TenantAdminUpdate
) -> tuple[Tenant, bool]:
    """Sửa name/slug/status. slug đổi → kiểm unique (409). Trả (tenant, slug_changed)."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise APIError(404, "TENANT_NOT_FOUND", "Không tìm thấy cửa hàng")

    slug_changed = False
    if data.slug is not None and data.slug != tenant.slug:
        existing = await tenant_service.get_tenant_by_slug(db, data.slug)
        if existing is not None and existing.id != tenant.id:
            raise APIError(409, "SLUG_EXISTS", "Mã cửa hàng (slug) đã tồn tại")
        tenant.slug = data.slug
        slug_changed = True
    if data.name is not None:
        tenant.name = data.name
    if data.status is not None and data.status != tenant.status:
        await _set_status(db, tenant, data.status)

    await db.commit()
    await db.refresh(tenant)
    return tenant, slug_changed


async def set_tenant_locked(
    db: AsyncSession, tenant_id: uuid.UUID, locked: bool
) -> Tenant:
    """Khóa (suspended) / mở (active) tenant. Khóa kèm revoke refresh (sống còn)."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise APIError(404, "TENANT_NOT_FOUND", "Không tìm thấy cửa hàng")
    await _set_status(db, tenant, "suspended" if locked else "active")
    await db.commit()
    await db.refresh(tenant)
    return tenant


async def reset_owner_password(
    db: AsyncSession, tenant_id: uuid.UUID, user_id: uuid.UUID | None = None
) -> tuple[str, str]:
    """Admin đặt lại MK owner của tenant. Trả (owner_phone, temp_password plaintext).

    users permissive-when-empty + refresh_tokens NGOÀI RLS → KHÔNG cần GUC. Sinh MK
    ngẫu nhiên + revoke refresh owner (buộc login lại). 0/nhiều owner → lỗi rõ."""
    tenant = await db.get(Tenant, tenant_id)
    if tenant is None:
        raise APIError(404, "TENANT_NOT_FOUND", "Không tìm thấy cửa hàng")

    owners = (
        await db.execute(
            select(User).where(
                User.tenant_id == tenant_id, User.role == "owner", User.status == "active"
            )
        )
    ).scalars().all()
    if user_id is not None:
        owner = next((o for o in owners if o.id == user_id), None)
        if owner is None:
            raise APIError(404, "OWNER_NOT_FOUND", "Không tìm thấy owner trong cửa hàng này")
    elif not owners:
        raise APIError(404, "NO_OWNER", "Cửa hàng không có owner đang hoạt động")
    elif len(owners) > 1:
        raise APIError(
            409, "MULTIPLE_OWNERS", "Cửa hàng có nhiều owner — cần chỉ định user_id"
        )
    else:
        owner = owners[0]

    temp_password = secrets.token_urlsafe(12)
    owner.password_hash = hash_password(temp_password)
    await db.execute(
        update(RefreshToken)
        .where(RefreshToken.user_id == owner.id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(timezone.utc))
    )
    await db.commit()
    return owner.phone, temp_password
