"""Branch business logic.

- Tạo branch: tự sinh code (B1, B2... theo thứ tự trong tenant) + tạo
  PostgreSQL sequence order_code_seq_{code} cho order_code (Stage 2 dùng).
- Soft delete qua status; chặn delete khi branch còn shift đang open.
- Mọi query filter tenant_id (multi-tenant).
"""
import re
import uuid

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.branch import Branch
from app.models.shift import Shift
from app.schemas.branch import BranchCreate, BranchUpdate

# code do hệ thống sinh: "B" + số. Validate trước khi nhúng vào tên sequence.
_SEQ_RE = re.compile(r"^order_code_seq_b[0-9]+$")

# order_prefix do owner đặt: chỉ chữ/số (không dấu, không khoảng trắng/ký tự đặc biệt).
_PREFIX_RE = re.compile(r"^[A-Za-z0-9]+$")
_PREFIX_MAX = 16


def _sequence_name(code: str) -> str:
    """Tên sequence order_code cho branch, vd B1 -> order_code_seq_b1 (lowercase)."""
    name = f"order_code_seq_{code.lower()}"
    if not _SEQ_RE.match(name):
        raise APIError(500, "INVALID_BRANCH_CODE", "Mã chi nhánh không hợp lệ")
    return name


def _normalize_prefix(raw: str | None) -> str:
    """Chuẩn hóa + validate định dạng prefix. Sai → 422 INVALID_PREFIX."""
    prefix = (raw or "").strip()
    if not prefix or len(prefix) > _PREFIX_MAX or not _PREFIX_RE.match(prefix):
        raise APIError(
            422,
            "INVALID_PREFIX",
            "Tiền tố chỉ gồm chữ và số (không dấu, không khoảng trắng/ký tự đặc "
            "biệt), tối đa 16 ký tự",
        )
    return prefix


async def _prefix_taken(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    prefix: str,
    *,
    exclude_id: uuid.UUID | None = None,
) -> bool:
    """Prefix đã dùng cho branch KHÁC trong cùng tenant? (gồm cả branch soft-delete:
    order_code không tái sử dụng nên prefix phải duy nhất toàn tenant)."""
    stmt = select(Branch.id).where(
        Branch.tenant_id == tenant_id, Branch.order_prefix == prefix
    )
    if exclude_id is not None:
        stmt = stmt.where(Branch.id != exclude_id)
    return (await db.scalar(stmt)) is not None


async def list_branches(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: Pagination,
    *,
    only_branch_id: uuid.UUID | None = None,
) -> tuple[list[Branch], int]:
    """only_branch_id: giới hạn về 1 branch (staff/shipper chỉ thấy branch mình)."""
    base = select(Branch).where(Branch.tenant_id == tenant_id)
    if only_branch_id is not None:
        base = base.where(Branch.id == only_branch_id)
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Branch.code).limit(page.limit).offset(page.offset)
    )
    return list(result.scalars().all()), total


async def get_branch(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    branch_id: uuid.UUID,
    *,
    only_branch_id: uuid.UUID | None = None,
) -> Branch:
    stmt = select(Branch).where(Branch.tenant_id == tenant_id, Branch.id == branch_id)
    branch = (await db.execute(stmt)).scalar_one_or_none()
    if branch is None or (only_branch_id is not None and branch.id != only_branch_id):
        raise APIError(404, "BRANCH_NOT_FOUND", "Không tìm thấy chi nhánh")
    return branch


async def create_branch(
    db: AsyncSession, tenant_id: uuid.UUID, data: BranchCreate
) -> Branch:
    # Đếm TẤT CẢ branch của tenant (kể cả đã soft-delete) để code không bị tái sử dụng.
    count = await db.scalar(
        select(func.count()).select_from(Branch).where(Branch.tenant_id == tenant_id)
    )
    code = f"B{(count or 0) + 1}"
    # Prefix mặc định = code. Hiếm khi owner đã đặt prefix tùy biến TRÙNG code mới
    # này cho branch khác → chặn sớm (clean error) thay vì 500 từ unique index.
    if await _prefix_taken(db, tenant_id, code):
        raise APIError(
            409,
            "PREFIX_TAKEN",
            f"Tiền tố mặc định '{code}' đã dùng cho chi nhánh khác; đổi tiền tố đó trước.",
        )
    branch = Branch(
        tenant_id=tenant_id,
        name=data.name,
        address=data.address,
        phone=data.phone,
        code=code,
        order_prefix=code,
        status="active",
    )
    db.add(branch)
    await db.flush()
    # Sequence riêng cho order_code của branch (CLAUDE.md ORDER #5).
    await db.execute(text(f'CREATE SEQUENCE IF NOT EXISTS "{_sequence_name(code)}" START 1'))
    await db.commit()
    await db.refresh(branch)
    return branch


async def update_branch(
    db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID, data: BranchUpdate
) -> Branch:
    branch = await get_branch(db, tenant_id, branch_id)
    fields = data.model_dump(exclude_unset=True)
    if "order_prefix" in fields:
        prefix = _normalize_prefix(fields["order_prefix"])
        if await _prefix_taken(db, tenant_id, prefix, exclude_id=branch_id):
            raise APIError(422, "PREFIX_TAKEN", "Tiền tố đã được dùng cho chi nhánh khác")
        fields["order_prefix"] = prefix  # đổi prefix CHỈ ảnh hưởng đơn MỚI
    for field, value in fields.items():
        setattr(branch, field, value)
    await db.commit()
    await db.refresh(branch)
    return branch


async def soft_delete_branch(
    db: AsyncSession, tenant_id: uuid.UUID, branch_id: uuid.UUID
) -> Branch:
    """Soft delete: đổi status. Chặn nếu còn shift đang open."""
    branch = await get_branch(db, tenant_id, branch_id)
    open_shift = await db.scalar(
        select(Shift.id).where(Shift.branch_id == branch_id, Shift.status == "open")
    )
    if open_shift is not None:
        raise APIError(
            409, "BRANCH_HAS_OPEN_SHIFT", "Chi nhánh còn ca đang mở, không thể xóa"
        )
    branch.status = "inactive"
    await db.commit()
    await db.refresh(branch)
    return branch
