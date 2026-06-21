"""CRUD price_rules + phân giải rule tự áp theo ngày (Stage 5.4).

Owner ghi (tạo/sửa/xóa-soft); mọi role đọc applicable (POS điền sẵn). Soft delete
qua is_active. Quy tắc tự áp: rule ACTIVE có [start_date, end_date] phủ NGÀY VN
hiện tại; nếu nhiều rule cùng loại → lấy rule mới nhất (start_date, created_at desc).
"""
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.price_rule import PriceRule
from app.schemas.price_rule import PriceRuleCreate, PriceRuleUpdate

_VN_OFFSET = timedelta(hours=7)


def vn_today() -> date:
    """Ngày hiện tại theo giờ Việt Nam (UTC+7) — mốc tính rule tự áp."""
    return (datetime.now(timezone.utc) + _VN_OFFSET).date()


def _validate(value_type: str | None, value: Decimal | None,
              start: date | None, end: date | None) -> None:
    if start is not None and end is not None and end < start:
        raise APIError(422, "INVALID_DATE_RANGE", "Ngày kết thúc phải >= ngày bắt đầu")
    if value_type == "percent" and value is not None and value > 100:
        raise APIError(422, "PERCENT_TOO_HIGH", "Phần trăm không được vượt 100")


async def list_rules(
    db: AsyncSession,
    tenant_id: uuid.UUID,
    page: Pagination,
    *,
    include_inactive: bool = True,
) -> tuple[list[PriceRule], int]:
    base = select(PriceRule).where(PriceRule.tenant_id == tenant_id)
    if not include_inactive:
        base = base.where(PriceRule.is_active.is_(True))
    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(PriceRule.start_date.desc(), PriceRule.created_at.desc())
        .limit(page.limit)
        .offset(page.offset)
    )
    return list(result.scalars().all()), total


async def get_rule(
    db: AsyncSession, tenant_id: uuid.UUID, rule_id: uuid.UUID
) -> PriceRule:
    rule = await db.scalar(
        select(PriceRule).where(
            PriceRule.tenant_id == tenant_id, PriceRule.id == rule_id
        )
    )
    if rule is None:
        raise APIError(404, "PRICE_RULE_NOT_FOUND", "Không tìm thấy quy tắc giá")
    return rule


async def create_rule(
    db: AsyncSession, tenant_id: uuid.UUID, data: PriceRuleCreate
) -> PriceRule:
    _validate(data.value_type, data.value, data.start_date, data.end_date)
    rule = PriceRule(
        tenant_id=tenant_id,
        type=data.type,
        value_type=data.value_type,
        value=data.value,
        name=data.name.strip(),
        start_date=data.start_date,
        end_date=data.end_date,
        is_active=True,
    )
    db.add(rule)
    await db.commit()
    return await get_rule(db, tenant_id, rule.id)


async def update_rule(
    db: AsyncSession, tenant_id: uuid.UUID, rule_id: uuid.UUID, data: PriceRuleUpdate
) -> PriceRule:
    rule = await get_rule(db, tenant_id, rule_id)
    changes = data.model_dump(exclude_unset=True)
    # Validate khoảng ngày + percent với giá trị HỢP NHẤT (mới nếu có, cũ nếu không).
    _validate(
        changes.get("value_type", rule.value_type),
        changes.get("value", rule.value),
        changes.get("start_date", rule.start_date),
        changes.get("end_date", rule.end_date),
    )
    if "name" in changes and changes["name"]:
        changes["name"] = changes["name"].strip()
    for field, value in changes.items():
        setattr(rule, field, value)
    await db.commit()
    return await get_rule(db, tenant_id, rule_id)


async def delete_rule(
    db: AsyncSession, tenant_id: uuid.UUID, rule_id: uuid.UUID
) -> PriceRule:
    """XÓA HẲN quy tắc (hard delete). KHÁC "Ẩn/Bật" (is_active toggle = tắt tạm).

    An toàn: 0 FK trỏ price_rules — đơn cũ SNAPSHOT surcharge/discount amount + reason
    (text) lúc tạo, KHÔNG phụ thuộc rule → xóa rule không ảnh hưởng đơn cũ.
    get_rule lọc tenant_id (404 nếu khác tenant). Lấy bản ghi TRƯỚC khi xóa để trả về.
    """
    rule = await get_rule(db, tenant_id, rule_id)
    await db.execute(
        delete(PriceRule).where(
            PriceRule.id == rule_id, PriceRule.tenant_id == tenant_id
        )
    )
    await db.commit()
    return rule


async def applicable_rule(
    db: AsyncSession, tenant_id: uuid.UUID, rule_type: str, on: date
) -> PriceRule | None:
    """Rule ACTIVE của loại `rule_type` phủ ngày `on`; nhiều rule → mới nhất."""
    return await db.scalar(
        select(PriceRule)
        .where(
            PriceRule.tenant_id == tenant_id,
            PriceRule.type == rule_type,
            PriceRule.is_active.is_(True),
            PriceRule.start_date <= on,
            PriceRule.end_date >= on,
        )
        .order_by(PriceRule.start_date.desc(), PriceRule.created_at.desc())
        .limit(1)
    )


async def get_applicable(
    db: AsyncSession, tenant_id: uuid.UUID, on: date | None = None
) -> dict:
    on = on or vn_today()
    return {
        "date": on,
        "surcharge": await applicable_rule(db, tenant_id, "surcharge", on),
        "discount": await applicable_rule(db, tenant_id, "discount", on),
    }
