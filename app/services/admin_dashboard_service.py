"""Dashboard tổng quan Super Admin (chỉ-đọc).

⚠️ ĐẾM XUYÊN TENANT trên bảng STRICT RLS (orders/branches): TÁI DÙNG pattern
list_tenants_with_stats — LOOP set_config GUC=tenant rồi cộng (KHÔNG bypass, KHÔNG
owner-engine). users = permissive-when-empty → đếm TOÀN CỤC 1 query (GUC rỗng).
tenants/subscriptions NGOÀI RLS → đọc thẳng.

Timezone: "hôm nay/tháng" theo GIỜ VN (UTC+7) — biên ngày = VN-midnight (KHÔNG UTC-midnight).
"""
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.models.branch import Branch
from app.models.order import Order
from app.models.tenant import Tenant
from app.models.user import User
from app.schemas.admin import DashboardOut, ExpiringItem, RecentTenantItem
from app.services import branch_service, price_rule_service

_settings = get_settings()
_SET_GUC = "SELECT set_config('app.current_tenant_id', :tid, true)"  # is_local (như A2)
_VN_TZ = timezone(timedelta(hours=7))  # giờ VN cho biên "hôm nay/tháng"


def _vn_start_today() -> datetime:
    """Mốc 00:00 GIỜ VN của hôm nay (tz-aware) — so với Order.created_at (UTC) Postgres tự quy đổi."""
    return datetime.combine(price_rule_service.vn_today(), time.min, tzinfo=_VN_TZ)


def _vn_start_month() -> datetime:
    return datetime.combine(price_rule_service.vn_today().replace(day=1), time.min, tzinfo=_VN_TZ)


async def get_dashboard(db: AsyncSession) -> DashboardOut:
    start_today = _vn_start_today()
    start_month = _vn_start_month()

    # ── Ngoài RLS: tổng tenant theo status (1 query) ──
    status_rows = (
        await db.execute(select(Tenant.status, func.count()).group_by(Tenant.status))
    ).all()
    tenants_by_status = {s: c for s, c in status_rows}

    # users permissive-when-empty → đếm TOÀN CỤC 1 query (GUC admin rỗng OK).
    users_active = (
        await db.scalar(select(func.count()).select_from(User).where(User.status == "active"))
    ) or 0

    # ── ⚠️ STRICT RLS: LOOP set_config per tenant rồi CỘNG (orders/branches) ──
    # subscriptions CŨNG strict → đọc hạn TRONG loop (GUC=tenant) qua subscription_info,
    # KHÔNG đọc cross-tenant ngoài loop (GUC rỗng → RLS chặn). Tenant cần chú ý gom luôn đây.
    tenants = (await db.execute(select(Tenant))).scalars().all()
    orders_today = orders_month = branches_active = 0
    expiring: list[ExpiringItem] = []
    for t in tenants:
        await db.execute(text(_SET_GUC), {"tid": str(t.id)})  # GUC=tenant cho strict
        sq_today = (
            select(func.count()).select_from(Order)
            .where(Order.tenant_id == t.id, Order.created_at >= start_today)
        ).scalar_subquery()
        sq_month = (
            select(func.count()).select_from(Order)
            .where(Order.tenant_id == t.id, Order.created_at >= start_month)
        ).scalar_subquery()
        sq_branch = (
            select(func.count()).select_from(Branch)
            .where(Branch.tenant_id == t.id, Branch.status == "active")
        ).scalar_subquery()
        ot, om, ba = (await db.execute(select(sq_today, sq_month, sq_branch))).one()
        orders_today += ot or 0
        orders_month += om or 0
        branches_active += ba or 0
        # Hạn gói: subscription_info đọc subscriptions dưới GUC=tenant (tái dùng stage expiry).
        sub = await branch_service.subscription_info(db, t.id)
        if sub.expires_at is not None and sub.expiry_status in ("warning", "grace", "expired"):
            expiring.append(ExpiringItem(
                tenant_id=t.id, name=t.name, slug=t.slug,
                expires_at=sub.expires_at, expiry_status=sub.expiry_status, days_left=sub.days_left,
            ))
    await db.execute(text(_SET_GUC), {"tid": ""})  # reset GUC sau loop (không rò sang request sau)
    expiring.sort(key=lambda e: e.expires_at)  # gần hết hạn → trước

    # ── Tenant mới tạo gần đây (ngoài RLS) ──
    recent = (
        await db.execute(select(Tenant).order_by(Tenant.created_at.desc()).limit(5))
    ).scalars().all()
    recent_tenants = [
        RecentTenantItem(id=t.id, name=t.name, slug=t.slug, status=t.status, created_at=t.created_at)
        for t in recent
    ]

    return DashboardOut(
        tenants_by_status=tenants_by_status,
        orders_today=orders_today, orders_month=orders_month,
        branches_active=branches_active, users_active=users_active,
        expiring=expiring, recent_tenants=recent_tenants,
    )
