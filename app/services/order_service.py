"""Order business logic.

QUY TẮC (CLAUDE.md ORDER):
- order_code: prefix branch + sequence per branch -> B1-00001 (nextval, KHÔNG MAX()+1).
- total_amount = SUM(subtotal items), tính ở SERVER, không tin client.
- Trạng thái tiến: created→washing→drying→ready→delivered→completed; cancelled
  từ mọi trạng thái TRƯỚC delivered; completed/cancelled là cuối (bất biến).
- Không sửa total_amount khi đơn đã có payment; sửa items chỉ khi chưa có
  payment và chưa tới 'ready'. Recompute total sau khi đổi items.
- DELETE = cancel (soft). Mọi query filter tenant_id (từ token).
"""
import re
import uuid
from datetime import datetime
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.customer import Customer
from app.models.log import OrderTrackingLog
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.user import User
from app.schemas.order import OrderCreate, OrderItemIn, OrderUpdate
from app.services import branch_service
from app.services.scope import resolve_write_branch

# State machine: bước tiến hợp lệ kế tiếp của mỗi trạng thái.
_FORWARD = {
    "created": "washing",
    "washing": "drying",
    "drying": "ready",
    "ready": "delivered",
    "delivered": "completed",
}
_CANCELLABLE_FROM = {"created", "washing", "drying", "ready"}
_TERMINAL = {"completed", "cancelled"}
# Items chỉ sửa được khi đơn chưa tới 'ready'.
_ITEMS_EDITABLE = {"created", "washing", "drying"}

_SEQ_RE = re.compile(r"^order_code_seq_b[0-9]+$")


def _sequence_name(branch_code: str) -> str:
    name = f"order_code_seq_{branch_code.lower()}"
    if not _SEQ_RE.match(name):
        raise APIError(500, "INVALID_BRANCH_CODE", "Mã chi nhánh không hợp lệ")
    return name


def _subtotal(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """VND không số lẻ -> quantize về số nguyên (round half up)."""
    return (quantity * unit_price).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _total(order: Order) -> Decimal:
    return sum((i.subtotal for i in order.items), Decimal(0))


def _add_tracking(db: AsyncSession, order: Order, status: str, actor: User) -> None:
    db.add(OrderTrackingLog(order_id=order.id, status=status, changed_by=actor.id))


def _validate_transition(current: str, new: str) -> None:
    if current in _TERMINAL:
        raise APIError(409, "INVALID_STATUS_TRANSITION", "Đơn đã ở trạng thái cuối")
    if new == "cancelled":
        if current not in _CANCELLABLE_FROM:
            raise APIError(
                409, "INVALID_STATUS_TRANSITION", "Không thể hủy đơn ở trạng thái này"
            )
        return
    if _FORWARD.get(current) == new:
        return
    raise APIError(409, "INVALID_STATUS_TRANSITION", "Chuyển trạng thái không hợp lệ")


async def _ensure_customer(
    db: AsyncSession, tenant_id: uuid.UUID, customer_id: uuid.UUID
) -> None:
    found = await db.scalar(
        select(Customer.id).where(
            Customer.tenant_id == tenant_id, Customer.id == customer_id
        )
    )
    if found is None:
        raise APIError(404, "CUSTOMER_NOT_FOUND", "Không tìm thấy khách hàng")


async def _has_payment(db: AsyncSession, order_id: uuid.UUID) -> bool:
    found = await db.scalar(
        select(Payment.id).where(Payment.order_id == order_id).limit(1)
    )
    return found is not None


async def _next_order_code(db: AsyncSession, branch) -> str:
    seq = _sequence_name(branch.code)  # đã validate -> an toàn để nhúng
    val = await db.scalar(text(f"SELECT nextval('{seq}')"))
    return f"{branch.code}-{int(val):05d}"


async def _get_order(db: AsyncSession, actor: User, order_id: uuid.UUID) -> Order:
    order = await db.scalar(
        select(Order).where(Order.tenant_id == actor.tenant_id, Order.id == order_id)
    )
    if order is None or (actor.role != "owner" and order.branch_id != actor.branch_id):
        raise APIError(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn")
    return order


async def _assert_items_editable(db: AsyncSession, order: Order) -> None:
    if await _has_payment(db, order.id):
        raise APIError(409, "ORDER_HAS_PAYMENT", "Đơn đã có payment, không sửa hạng mục")
    if order.order_status not in _ITEMS_EDITABLE:
        raise APIError(
            409, "ORDER_ITEMS_LOCKED", "Đơn đã tới ready/đã đóng, không sửa hạng mục"
        )


# ── create ──────────────────────────────────────────────────────────────────
async def create_order(db: AsyncSession, actor: User, data: OrderCreate) -> Order:
    branch_id = resolve_write_branch(actor, data.branch_id)
    branch = await branch_service.get_branch(db, actor.tenant_id, branch_id)
    if data.customer_id is not None:
        await _ensure_customer(db, actor.tenant_id, data.customer_id)

    order = Order(
        tenant_id=actor.tenant_id,
        branch_id=branch_id,
        customer_id=data.customer_id,
        order_code=await _next_order_code(db, branch),
        notes=data.notes,
        created_by=actor.id,
        order_status="created",
        payment_status="unpaid",
    )
    for it in data.items:
        order.items.append(
            OrderItem(
                service_name=it.service_name,
                quantity=it.quantity,
                unit_price=it.unit_price,
                subtotal=_subtotal(it.quantity, it.unit_price),
            )
        )
    order.total_amount = _total(order)
    db.add(order)
    await db.flush()  # cần order.id cho tracking log
    _add_tracking(db, order, "created", actor)
    await db.commit()
    return await _get_order(db, actor, order.id)


# ── status transition ───────────────────────────────────────────────────────
async def change_status(
    db: AsyncSession, actor: User, order_id: uuid.UUID, new_status: str
) -> Order:
    order = await _get_order(db, actor, order_id)
    _validate_transition(order.order_status, new_status)
    order.order_status = new_status
    await db.flush()
    _add_tracking(db, order, new_status, actor)
    await db.commit()
    return await _get_order(db, actor, order_id)


async def cancel_order(db: AsyncSession, actor: User, order_id: uuid.UUID) -> Order:
    """DELETE = soft cancel. Áp dụng đúng luật transition (delivered/completed -> 409)."""
    return await change_status(db, actor, order_id, "cancelled")


# ── update (notes/customer/total) ───────────────────────────────────────────
async def update_order(
    db: AsyncSession, actor: User, order_id: uuid.UUID, data: OrderUpdate
) -> Order:
    order = await _get_order(db, actor, order_id)
    changes = data.model_dump(exclude_unset=True)

    if changes.get("total_amount") is not None:
        if await _has_payment(db, order_id):
            raise APIError(
                409, "ORDER_HAS_PAYMENT", "Đơn đã có payment, không sửa total_amount"
            )
        order.total_amount = changes["total_amount"]
    if "customer_id" in changes:
        if changes["customer_id"] is not None:
            await _ensure_customer(db, actor.tenant_id, changes["customer_id"])
        order.customer_id = changes["customer_id"]
    if "notes" in changes:
        order.notes = changes["notes"]

    await db.commit()
    return await _get_order(db, actor, order_id)


# ── items ───────────────────────────────────────────────────────────────────
async def add_item(
    db: AsyncSession, actor: User, order_id: uuid.UUID, item: OrderItemIn
) -> Order:
    order = await _get_order(db, actor, order_id)
    await _assert_items_editable(db, order)
    order.items.append(
        OrderItem(
            service_name=item.service_name,
            quantity=item.quantity,
            unit_price=item.unit_price,
            subtotal=_subtotal(item.quantity, item.unit_price),
        )
    )
    order.total_amount = _total(order)
    await db.commit()
    return await _get_order(db, actor, order_id)


async def update_item(
    db: AsyncSession,
    actor: User,
    order_id: uuid.UUID,
    item_id: uuid.UUID,
    item: OrderItemIn,
) -> Order:
    order = await _get_order(db, actor, order_id)
    await _assert_items_editable(db, order)
    target = next((i for i in order.items if i.id == item_id), None)
    if target is None:
        raise APIError(404, "ORDER_ITEM_NOT_FOUND", "Không tìm thấy hạng mục")
    target.service_name = item.service_name
    target.quantity = item.quantity
    target.unit_price = item.unit_price
    target.subtotal = _subtotal(item.quantity, item.unit_price)
    order.total_amount = _total(order)
    await db.commit()
    return await _get_order(db, actor, order_id)


async def delete_item(
    db: AsyncSession, actor: User, order_id: uuid.UUID, item_id: uuid.UUID
) -> Order:
    order = await _get_order(db, actor, order_id)
    await _assert_items_editable(db, order)
    target = next((i for i in order.items if i.id == item_id), None)
    if target is None:
        raise APIError(404, "ORDER_ITEM_NOT_FOUND", "Không tìm thấy hạng mục")
    order.items.remove(target)  # cascade delete-orphan -> xóa dòng
    order.total_amount = _total(order)
    await db.commit()
    return await _get_order(db, actor, order_id)


# ── read ────────────────────────────────────────────────────────────────────
async def get_order(db: AsyncSession, actor: User, order_id: uuid.UUID) -> Order:
    return await _get_order(db, actor, order_id)


async def get_order_by_code(db: AsyncSession, actor: User, order_code: str) -> Order:
    order = await db.scalar(
        select(Order).where(
            Order.tenant_id == actor.tenant_id, Order.order_code == order_code
        )
    )
    if order is None or (actor.role != "owner" and order.branch_id != actor.branch_id):
        raise APIError(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn")
    return order


async def list_orders(
    db: AsyncSession,
    actor: User,
    page: Pagination,
    *,
    branch_id: uuid.UUID | None = None,
    order_status: str | None = None,
    customer_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
) -> tuple[list[Order], int]:
    base = select(Order).where(Order.tenant_id == actor.tenant_id)
    if actor.role != "owner":
        base = base.where(Order.branch_id == actor.branch_id)
    elif branch_id is not None:
        base = base.where(Order.branch_id == branch_id)
    if order_status is not None:
        base = base.where(Order.order_status == order_status)
    if customer_id is not None:
        base = base.where(Order.customer_id == customer_id)
    if date_from is not None:
        base = base.where(Order.created_at >= date_from)
    if date_to is not None:
        base = base.where(Order.created_at <= date_to)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Order.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return list(result.scalars().all()), total
