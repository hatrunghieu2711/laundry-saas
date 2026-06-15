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
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import func, or_, select, text
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.deps import Pagination
from app.core.errors import APIError
from app.models.customer import Customer
from app.models.log import OrderTrackingLog
from app.models.order import Order, OrderItem
from app.models.payment import Payment
from app.models.user import User
from app.schemas.order import OrderCreate, OrderItemIn, OrderUpdate
from app.services import branch_service, service_service
from app.services.pricing import price_line
from app.services.scope import resolve_write_branch

# State machine: bước tiến hợp lệ kế tiếp của mỗi trạng thái.
_FORWARD = {
    "created": "washing",
    "washing": "drying",
    "drying": "ready",
    "ready": "delivered",
    "delivered": "completed",
}
# Nhóm xử lý tại tiệm (có thứ tự) — cho LÙI tự do về bước trước trong nhóm.
_PROCESSING = ["created", "washing", "drying", "ready"]
_CANCELLABLE_FROM = {"created", "washing", "drying", "ready"}
_TERMINAL = {"completed", "cancelled"}
# Items chỉ sửa được khi đơn chưa tới 'ready'.
_ITEMS_EDITABLE = {"created", "washing", "drying"}
# Trạng thái đơn còn hoạt động — hiển thị trên dashboard vận hành (ẩn terminal).
_BOARD_STATUSES = ["created", "washing", "drying", "ready", "delivered"]

_SEQ_RE = re.compile(r"^order_code_seq_b[0-9]+$")


def _sequence_name(branch_code: str) -> str:
    name = f"order_code_seq_{branch_code.lower()}"
    if not _SEQ_RE.match(name):
        raise APIError(500, "INVALID_BRANCH_CODE", "Mã chi nhánh không hợp lệ")
    return name


def _subtotal(quantity: Decimal, unit_price: Decimal) -> Decimal:
    """VND không số lẻ -> quantize về số nguyên (round half up)."""
    return (quantity * unit_price).quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _assert_future(pickup_at: datetime) -> None:
    """Giờ hẹn giao phải ở tương lai (không hẹn quá khứ). Naive -> coi là UTC."""
    if pickup_at.tzinfo is None:
        pickup_at = pickup_at.replace(tzinfo=timezone.utc)
    if pickup_at <= datetime.now(timezone.utc):
        raise APIError(422, "PICKUP_AT_IN_PAST", "Giờ hẹn giao phải ở tương lai")


async def _build_item(
    db: AsyncSession, tenant_id: uuid.UUID, item: OrderItemIn
) -> OrderItem:
    """Dựng OrderItem (snapshot giá). service_id -> lấy giá từ bảng giá; ngược lại
    dùng giá nhập tay. service_name/unit_price/subtotal là SNAPSHOT bất biến."""
    if item.service_id is not None:
        service = await service_service.get_active_service(db, tenant_id, item.service_id)
        name, unit_price, subtotal = price_line(service, item.quantity)
        return OrderItem(
            service_id=service.id,
            service_name=name,
            quantity=item.quantity,
            unit_price=unit_price,
            subtotal=subtotal,
        )
    return OrderItem(
        service_name=item.service_name,
        quantity=item.quantity,
        unit_price=item.unit_price,
        subtotal=_subtotal(item.quantity, item.unit_price),
    )


def _total(order: Order) -> Decimal:
    return sum((i.subtotal for i in order.items), Decimal(0))


def _apply_search(stmt, q: str | None):
    """Lọc gần đúng theo mã đơn HOẶC tên khách (ILIKE). outerjoin customers
    vì đơn khách lẻ không có customer_id."""
    if not q or not q.strip():
        return stmt
    like = f"%{q.strip()}%"
    return stmt.outerjoin(Customer, Order.customer_id == Customer.id).where(
        or_(Order.order_code.ilike(like), Customer.full_name.ilike(like))
    )


def _add_tracking(db: AsyncSession, order: Order, status: str, actor: User) -> None:
    db.add(OrderTrackingLog(order_id=order.id, status=status, changed_by=actor.id))


def _validate_transition(order: Order, new: str) -> None:
    """Luật chuyển trạng thái (Stage 3.9 — cho LÙI có kiểm soát).

    - Tiến 1 bước: created→washing→…→completed.
    - Lùi tự do trong nhóm xử lý (created↔ready, chỉ về bước TRƯỚC).
    - delivered→ready: CHỈ khi payment_status='unpaid' (chưa thu).
    - completed/cancelled: khóa vĩnh viễn (ORDER_CLOSED).
    """
    current = order.order_status
    if current in _TERMINAL:
        raise APIError(409, "ORDER_CLOSED", "Đơn đã đóng (hoàn tất/đã hủy), không đổi trạng thái")
    if new == current:
        raise APIError(409, "INVALID_STATUS_TRANSITION", "Đơn đã ở trạng thái này")
    if new == "cancelled":
        if current not in _CANCELLABLE_FROM:
            raise APIError(
                409, "INVALID_STATUS_TRANSITION", "Không thể hủy đơn ở trạng thái này"
            )
        return
    # Tiến đúng 1 bước.
    if _FORWARD.get(current) == new:
        return
    # Lùi trong nhóm xử lý (chỉ về bước có index nhỏ hơn).
    if current in _PROCESSING and new in _PROCESSING:
        if _PROCESSING.index(new) < _PROCESSING.index(current):
            return
        raise APIError(409, "INVALID_STATUS_TRANSITION", "Chuyển trạng thái không hợp lệ")
    # Lùi giao hàng: delivered→ready chỉ khi chưa thu tiền.
    if current == "delivered" and new == "ready":
        if order.payment_status != "unpaid":
            raise APIError(
                409, "CANNOT_REVERT_PAID_DELIVERY", "Không thể lùi đơn đã thu tiền"
            )
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


def _format_order_code(prefix: str, seq_val: int) -> str:
    """Mã đơn = {prefix}-{số}. Số tối thiểu 5 chữ số (00001); :05d TỰ NỚI 6+ chữ
    số khi vượt 99999 (100000) — KHÔNG reset, KHÔNG đụng trần."""
    return f"{prefix}-{seq_val:05d}"


async def _next_order_code(db: AsyncSession, branch) -> str:
    # Sequence vẫn keyed theo CODE hệ thống (bất biến) — đổi prefix KHÔNG đụng sequence.
    seq = _sequence_name(branch.code)  # đã validate -> an toàn để nhúng
    val = await db.scalar(text(f"SELECT nextval('{seq}')"))
    prefix = branch.order_prefix or branch.code
    return _format_order_code(prefix, int(val))


async def _get_order(db: AsyncSession, actor: User, order_id: uuid.UUID) -> Order:
    order = await db.scalar(
        select(Order).where(Order.tenant_id == actor.tenant_id, Order.id == order_id)
    )
    if order is None or (actor.role != "owner" and order.branch_id != actor.branch_id):
        raise APIError(404, "ORDER_NOT_FOUND", "Không tìm thấy đơn")
    return order


async def _reload_order(db: AsyncSession, actor: User, order_id: uuid.UUID) -> Order:
    """Như _get_order nhưng populate_existing — lấy lại relationship sau khi đổi
    FK (vd customer_id) để customer_name không bị giá trị cũ."""
    result = await db.execute(
        select(Order)
        .options(
            selectinload(Order.items),
            selectinload(Order.created_by_user),
            selectinload(Order.customer),
        )
        .where(Order.tenant_id == actor.tenant_id, Order.id == order_id)
        .execution_options(populate_existing=True)
    )
    order = result.scalar_one_or_none()
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
    _assert_future(data.pickup_at)
    branch_id = resolve_write_branch(actor, data.branch_id)
    branch = await branch_service.get_branch(db, actor.tenant_id, branch_id)
    if data.customer_id is not None:
        await _ensure_customer(db, actor.tenant_id, data.customer_id)

    order = Order(
        tenant_id=actor.tenant_id,
        branch_id=branch_id,
        customer_id=data.customer_id,
        order_code=await _next_order_code(db, branch),
        pickup_at=data.pickup_at,
        notes=data.notes,
        created_by=actor.id,
        order_status="created",
        payment_status="unpaid",
    )
    for it in data.items:
        order.items.append(await _build_item(db, actor.tenant_id, it))
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
    _validate_transition(order, new_status)
    order.order_status = new_status
    await db.flush()
    _add_tracking(db, order, new_status, actor)
    await db.commit()
    result = await _get_order(db, actor, order_id)
    # Giao đơn nhưng chưa thu đủ -> báo UI ép hỏi thanh toán (KHÔNG chặn cứng:
    # ghi nợ có chủ đích là hợp lệ, lúc đó payment_status='debt' nên không cờ).
    if new_status == "delivered" and result.payment_status in ("unpaid", "partial"):
        result.requires_payment = True
    return result


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
    if changes.get("pickup_at") is not None:
        if order.order_status in _TERMINAL:
            raise APIError(
                409, "ORDER_CLOSED", "Đơn đã đóng, không sửa giờ hẹn giao"
            )
        order.pickup_at = changes["pickup_at"]
    if "notes" in changes:
        order.notes = changes["notes"]

    await db.commit()
    return await _reload_order(db, actor, order_id)


# ── items ───────────────────────────────────────────────────────────────────
async def add_item(
    db: AsyncSession, actor: User, order_id: uuid.UUID, item: OrderItemIn
) -> Order:
    order = await _get_order(db, actor, order_id)
    await _assert_items_editable(db, order)
    order.items.append(await _build_item(db, actor.tenant_id, item))
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
    built = await _build_item(db, actor.tenant_id, item)
    target.service_id = built.service_id
    target.service_name = built.service_name
    target.quantity = built.quantity
    target.unit_price = built.unit_price
    target.subtotal = built.subtotal
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
    order_status: list[str] | None = None,
    payment_status: list[str] | None = None,
    customer_id: uuid.UUID | None = None,
    date_from: datetime | None = None,
    date_to: datetime | None = None,
    q: str | None = None,
) -> tuple[list[Order], int]:
    base = select(Order).where(Order.tenant_id == actor.tenant_id)
    if actor.role != "owner":
        base = base.where(Order.branch_id == actor.branch_id)
    elif branch_id is not None:
        base = base.where(Order.branch_id == branch_id)
    if order_status:
        base = base.where(Order.order_status.in_(order_status))
    if payment_status:
        base = base.where(Order.payment_status.in_(payment_status))
    if customer_id is not None:
        base = base.where(Order.customer_id == customer_id)
    if date_from is not None:
        base = base.where(Order.created_at >= date_from)
    if date_to is not None:
        base = base.where(Order.created_at <= date_to)
    base = _apply_search(base, q)

    total = await db.scalar(select(func.count()).select_from(base.subquery())) or 0
    result = await db.execute(
        base.order_by(Order.created_at.desc()).limit(page.limit).offset(page.offset)
    )
    return list(result.scalars().all()), total


# ── dashboard vận hành (board) ───────────────────────────────────────────────
async def get_board(
    db: AsyncSession,
    actor: User,
    branch_id: uuid.UUID | None = None,
    q: str | None = None,
) -> dict:
    """Đơn đang hoạt động (ẩn completed/cancelled), nhóm theo order_status để
    frontend dựng cột; kèm cờ is_overdue mỗi đơn và summary đếm nhanh."""
    base = select(Order).where(
        Order.tenant_id == actor.tenant_id,
        Order.order_status.in_(_BOARD_STATUSES),
    )
    if actor.role != "owner":
        base = base.where(Order.branch_id == actor.branch_id)
    elif branch_id is not None:
        base = base.where(Order.branch_id == branch_id)
    base = _apply_search(base, q)

    result = await db.execute(base.order_by(Order.pickup_at.asc()))
    orders = list(result.scalars().all())

    now = datetime.now(timezone.utc)
    columns: dict[str, list[Order]] = {s: [] for s in _BOARD_STATUSES}
    summary = {"total_orders": 0, "unpaid": 0, "paid": 0, "debt": 0, "overdue": 0}
    for o in orders:
        # Trễ hẹn: quá giờ hẹn và đơn chưa giao (delivered đã rời tiệm -> không tính).
        o.is_overdue = o.pickup_at < now and o.order_status != "delivered"
        columns[o.order_status].append(o)
        summary["total_orders"] += 1
        if o.payment_status in ("unpaid", "partial"):
            summary["unpaid"] += 1
        elif o.payment_status == "paid":
            summary["paid"] += 1
        elif o.payment_status == "debt":
            summary["debt"] += 1
        if o.is_overdue:
            summary["overdue"] += 1
    return {"columns": columns, "summary": summary}
