"""Price rule endpoints (phụ thu/giảm tự áp theo ngày) — Stage 5.4.

owner ghi (tạo/sửa/xóa-soft); owner/manager liệt kê; mọi role đọc /applicable
(POS điền sẵn lúc tạo đơn). Tenant-scoped từ token.
"""
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status

from app.api.deps import DbSession, PageParams, require_role
from app.models.user import User
from app.schemas.common import Page
from app.schemas.price_rule import (
    ApplicableRules,
    PriceRuleCreate,
    PriceRuleOut,
    PriceRuleUpdate,
)
from app.services import price_rule_service

router = APIRouter(prefix="/price-rules", tags=["price-rules"])

Reader = Annotated[User, Depends(require_role("owner", "manager", "staff", "shipper"))]
Manager = Annotated[User, Depends(require_role("owner", "manager"))]
Owner = Annotated[User, Depends(require_role("owner"))]


@router.get("", response_model=Page[PriceRuleOut])
async def list_rules(actor: Manager, db: DbSession, page: PageParams) -> Page[PriceRuleOut]:
    items, total = await price_rule_service.list_rules(db, actor.tenant_id, page)
    return Page[PriceRuleOut](items=items, total=total, limit=page.limit, offset=page.offset)


# /applicable phải khai báo TRƯỚC /{rule_id} để không bị bắt nhầm path param.
@router.get("/applicable", response_model=ApplicableRules)
async def applicable(actor: Reader, db: DbSession) -> ApplicableRules:
    return await price_rule_service.get_applicable(db, actor.tenant_id)


@router.post("", response_model=PriceRuleOut, status_code=status.HTTP_201_CREATED)
async def create_rule(payload: PriceRuleCreate, actor: Owner, db: DbSession) -> PriceRuleOut:
    return await price_rule_service.create_rule(db, actor.tenant_id, payload)


@router.get("/{rule_id}", response_model=PriceRuleOut)
async def get_rule(rule_id: uuid.UUID, actor: Manager, db: DbSession) -> PriceRuleOut:
    return await price_rule_service.get_rule(db, actor.tenant_id, rule_id)


@router.put("/{rule_id}", response_model=PriceRuleOut)
async def update_rule(
    rule_id: uuid.UUID, payload: PriceRuleUpdate, actor: Owner, db: DbSession
) -> PriceRuleOut:
    return await price_rule_service.update_rule(db, actor.tenant_id, rule_id, payload)


@router.delete("/{rule_id}", response_model=PriceRuleOut)
async def delete_rule(rule_id: uuid.UUID, actor: Owner, db: DbSession) -> PriceRuleOut:
    """XÓA HẲN (hard delete) — khác "Ẩn/Bật" (PUT is_active). Đơn cũ snapshot nên
    không ảnh hưởng; 0 FK trỏ price_rules. Trả về bản ghi vừa xóa."""
    return await price_rule_service.delete_rule(db, actor.tenant_id, rule_id)
