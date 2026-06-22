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

from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import APIError
from app.core.security import hash_password
from app.models.branch import Branch
from app.models.tenant import Tenant
from app.models.tenant_settings import TenantSettings
from app.models.user import User
from app.schemas.admin import TenantCreate
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
