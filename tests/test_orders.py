"""Test order service: tạo đơn + items, order_code, transition trạng thái,
khóa sửa khi có payment, cancel, cách ly tenant. Viết TRƯỚC service (TDD)."""
import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import text

from app.core.database import SessionFactory
from app.models.customer import Customer
from app.models.payment import Payment
from tests.conftest import auth_headers, login

ORDERS = "/api/v1/orders"


def _num(x) -> int:
    return int(Decimal(str(x)))


def _pickup(hours: float = 4) -> str:
    """ISO giờ hẹn giao ở tương lai (mặc định +4h)."""
    return (datetime.now(timezone.utc) + timedelta(hours=hours)).isoformat()


@pytest_asyncio.fixture
async def octx(client: AsyncClient, owner: dict) -> dict:
    """Owner + 2 branch + staff ở branch A."""
    owner_token = await login(client, owner["phone"], owner["password"])

    async def _branch(name: str) -> dict:
        r = await client.post("/api/v1/branches", json={"name": name},
                              headers=auth_headers(owner_token))
        assert r.status_code == 201, r.text
        return r.json()

    branch_a = await _branch("CN A")
    branch_b = await _branch("CN B")
    r = await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000041", "password": "pass123",
              "role": "staff", "branch_id": branch_a["id"]},
        headers=auth_headers(owner_token),
    )
    assert r.status_code == 201, r.text
    return {
        "owner": owner,
        "owner_token": owner_token,
        "staff_token": await login(client, "0900000041", "pass123"),
        "branch_a": branch_a,
        "branch_b": branch_b,
    }


async def _create_order(client: AsyncClient, token: str, items: list[dict], **extra) -> dict:
    extra.setdefault("pickup_at", _pickup())
    body = {"items": items, **extra}
    return await client.post(ORDERS, json=body, headers=auth_headers(token))


_ITEMS = [
    {"service_name": "Giặt thường", "quantity": 2, "unit_price": 30000},
    {"service_name": "Giặt khô", "quantity": 1, "unit_price": 50000},
]


async def _open_shift(client: AsyncClient, token: str) -> str:
    r = await client.post("/api/v1/shifts/open", json={"opening_cash": 0},
                          headers=auth_headers(token))
    assert r.status_code == 201, r.text
    return r.json()["id"]


async def _insert_payment(octx: dict, shift_id: str, order_id: str, amount: int) -> None:
    async with SessionFactory() as db:
        db.add(Payment(
            tenant_id=octx["owner"]["tenant_id"],
            branch_id=uuid.UUID(octx["branch_a"]["id"]),
            order_id=uuid.UUID(order_id),
            shift_id=uuid.UUID(shift_id),
            amount=Decimal(amount),
            payment_method="cash",
            transaction_type="payment",
            created_by=octx["owner"]["user_id"],
        ))
        await db.commit()


async def _log_count(order_id: str) -> int:
    async with SessionFactory() as db:
        return await db.scalar(
            text("SELECT count(*) FROM order_tracking_logs WHERE order_id=:i"),
            {"i": order_id},
        )


async def _set_status(client: AsyncClient, token: str, oid: str, status: str):
    return await client.patch(f"{ORDERS}/{oid}/status", json={"order_status": status},
                              headers=auth_headers(token))


async def _advance_to_delivered(client: AsyncClient, token: str, oid: str, *, ps: str = "paid"):
    """Stage B: đưa đơn tới 'delivered' ĐÚNG LUẬT — thu/ghi-nợ TRƯỚC rồi mới giao
    (server chặn cứng giao đơn unpaid/partial). ps='paid' (mặc định) hoặc 'debt'."""
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, token, oid, st)
    await _set_order_db(oid, payment_status=ps)
    r = await _set_status(client, token, oid, "delivered")
    assert r.status_code == 200, r.text
    return r


# Tổng tiền của _ITEMS = 2*30000 + 1*50000.
_T_ITEMS = 110000


async def _cancel(client: AsyncClient, token: str, oid: str, *, reason="Khách đổi ý", refund=None):
    body: dict = {}
    if reason is not None:
        body["cancel_reason"] = reason
    if refund is not None:
        body["refund_amount"] = refund
    return await client.post(f"{ORDERS}/{oid}/cancel", json=body, headers=auth_headers(token))


async def _summary(client: AsyncClient, token: str, sid: str) -> dict:
    r = await client.get(f"/api/v1/shifts/{sid}/summary", headers=auth_headers(token))
    assert r.status_code == 200, r.text
    return r.json()


async def _prepaid_order(client: AsyncClient, token: str) -> str:
    """Đơn ĐÃ THU đủ qua prepay (cash) — cần ca đang mở."""
    r = await _create_order(client, token, _ITEMS, prepay=True, payment_method="cash")
    assert r.status_code == 201, r.text
    return r.json()["id"]


# ── tạo đơn ─────────────────────────────────────────────────────────────────
async def test_create_order_code_total_and_log(client: AsyncClient, octx: dict):
    r1 = await _create_order(client, octx["staff_token"], _ITEMS)
    assert r1.status_code == 201, r1.text
    b1 = r1.json()
    assert b1["order_code"] == "B1-00001"
    assert b1["order_status"] == "created"
    assert b1["payment_status"] == "unpaid"
    assert _num(b1["total_amount"]) == 110000  # 2*30000 + 1*50000
    assert len(b1["items"]) == 2
    assert b1["created_by_name"] == "NV A"  # tên người tạo nhúng sẵn

    # order_code tuần tự.
    r2 = await _create_order(client, octx["staff_token"], _ITEMS)
    assert r2.json()["order_code"] == "B1-00002"

    # tracking log dòng đầu = 'created'.
    assert await _log_count(b1["id"]) == 1


async def test_total_ignores_client_quantity_decimal(client: AsyncClient, octx: dict):
    items = [{"service_name": "Giặt kg", "quantity": 1.5, "unit_price": 20000}]
    r = await _create_order(client, octx["staff_token"], items)
    assert r.status_code == 201, r.text
    assert _num(r.json()["total_amount"]) == 30000  # 1.5 * 20000


# ── transition trạng thái ───────────────────────────────────────────────────
async def test_status_full_forward_flow(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        resp = await _set_status(client, t, oid, st)
        assert resp.status_code == 200, resp.text
        assert resp.json()["order_status"] == st
    await _set_order_db(oid, payment_status="paid")  # Stage B: thu đủ trước khi giao
    for st in ["delivered", "completed"]:
        resp = await _set_status(client, t, oid, st)
        assert resp.status_code == 200, resp.text
        assert resp.json()["order_status"] == st
    # 1 (created) + 5 transition = 6 dòng log (set payment_status qua DB không ghi log).
    assert await _log_count(oid) == 6


async def test_status_backward_forbidden(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_delivered(client, t, oid)
    resp = await _set_status(client, t, oid, "washing")  # delivered -> washing: cấm
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


async def test_status_skip_forward_forbidden(client: AsyncClient, octx: dict):
    # Nhảy RA NGOÀI nhóm xử lý tại tiệm vẫn CẤM (không bỏ qua delivered / vào trạng thái cuối).
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    r1 = await _set_status(client, t, oid, "delivered")  # created -> delivered (bỏ qua ready)
    assert r1.status_code == 409
    assert r1.json()["code"] == "INVALID_STATUS_TRANSITION"
    r2 = await _set_status(client, t, oid, "completed")  # created -> completed
    assert r2.status_code == 409
    assert r2.json()["code"] == "INVALID_STATUS_TRANSITION"


async def test_forward_jump_within_processing_group_allowed(client: AsyncClient, octx: dict):
    # Stage 6.17: nhảy TIẾN trong nhóm xử lý trong 1 request (nút → qua cột gộp washing+drying).
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _set_status(client, t, oid, "washing")
    r = await _set_status(client, t, oid, "ready")  # washing -> ready (nhảy qua drying)
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "ready"
    # created -> ready (nhảy nhiều bước trong nhóm) cũng OK.
    oid2 = (await _create_order(client, t, _ITEMS)).json()["id"]
    r2 = await _set_status(client, t, oid2, "ready")
    assert r2.status_code == 200, r2.text
    assert r2.json()["order_status"] == "ready"


async def test_completed_is_terminal(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_delivered(client, t, oid)
    await _set_status(client, t, oid, "completed")
    resp = await _set_status(client, t, oid, "washing")
    assert resp.status_code == 409
    assert resp.json()["code"] == "ORDER_CLOSED"


# ── Stage 3.9: lùi trạng thái có kiểm soát ──────────────────────────────────
async def test_revert_within_processing_group(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, t, oid, st)
    # lùi từng bước ready->drying->washing->created
    for st in ["drying", "washing", "created"]:
        r = await _set_status(client, t, oid, st)
        assert r.status_code == 200, r.text
        assert r.json()["order_status"] == st


async def test_revert_multistep_back_allowed(client: AsyncClient, octx: dict):
    # Lùi nhiều bước một lần trong nhóm xử lý: ready -> created.
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, t, oid, st)
    r = await _set_status(client, t, oid, "created")
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "created"


# (Stage B) BỎ test_revert_delivered_unpaid_ok: không còn tình huống "delivered + unpaid"
# (server chặn cứng giao đơn chưa thu) → đơn delivered luôn paid/debt; undo xét ở test dưới.


async def test_revert_delivered_paid_now_allowed(client: AsyncClient, octx: dict):
    # Stage 6.18: UNDO giao — delivered→ready cho phép MỌI payment_status (chỉ đổi
    # trạng thái, KHÔNG đụng tiền). (Stage B: chỉ đơn paid/debt mới giao được nên chỉ xét 2.)
    t = octx["staff_token"]
    for ps in ["paid", "debt"]:
        oid = (await _create_order(client, t, _ITEMS)).json()["id"]
        await _advance_to_delivered(client, t, oid, ps=ps)  # thu/ghi-nợ trước rồi giao
        r = await _set_status(client, t, oid, "ready")
        assert r.status_code == 200, f"{ps}: {r.text}"
        assert r.json()["order_status"] == "ready"
        assert r.json()["payment_status"] == ps  # KHÔNG đụng tiền


async def test_revert_completed_locked(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_delivered(client, t, oid)
    await _set_status(client, t, oid, "completed")
    r = await _set_status(client, t, oid, "ready")
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_CLOSED"


async def test_revert_cancelled_locked(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _cancel(client, t, oid, refund=0)  # -> cancelled
    r = await _set_status(client, t, oid, "created")
    assert r.status_code == 409
    assert r.json()["code"] == "ORDER_CLOSED"


async def test_revert_writes_tracking_log(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying"]:
        await _set_status(client, t, oid, st)
    before = await _log_count(oid)  # created+washing+drying = 3
    await _set_status(client, t, oid, "washing")  # lùi drying->washing
    assert await _log_count(oid) == before + 1
    # dòng log mới nhất = 'washing', có changed_by
    async with SessionFactory() as db:
        row = (
            await db.execute(
                text(
                    "SELECT status, changed_by FROM order_tracking_logs "
                    "WHERE order_id=:i ORDER BY created_at DESC LIMIT 1"
                ),
                {"i": oid},
            )
        ).first()
    assert row[0] == "washing"
    assert row[1] is not None


# ── Stage 6.41: GET /orders/{id} kèm tracking (timeline tab Lịch sử) ─────────
async def test_get_order_includes_tracking(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, t, oid, st)
    r = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    tr = r.json()["tracking"]
    assert [e["status"] for e in tr] == ["created", "washing", "drying", "ready"]
    assert all(e["at"] for e in tr)  # mỗi mốc có thời gian


# ── Stage 6.47: GET /orders?sort=updated_at (tab Lịch sử) ───────────────────
async def test_list_sort_updated_at(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    a = (await _create_order(client, t, _ITEMS)).json()  # tạo TRƯỚC
    b = (await _create_order(client, t, _ITEMS)).json()  # tạo SAU
    # mặc định created_at desc → b (mới tạo) đứng trước a
    ids = [o["id"] for o in (await client.get(f"{ORDERS}?limit=50", headers=auth_headers(t))).json()["items"]]
    assert ids.index(b["id"]) < ids.index(a["id"])
    # CHẠM a (đổi trạng thái → updated_at bump) rồi sort=updated_at → a lên trước b
    await _set_status(client, t, a["id"], "washing")
    ids2 = [o["id"] for o in (await client.get(f"{ORDERS}?sort=updated_at&limit=50", headers=auth_headers(t))).json()["items"]]
    assert ids2.index(a["id"]) < ids2.index(b["id"])


# ── Stage 3.9: search q (mã đơn HOẶC tên khách) ─────────────────────────────
async def test_list_search_q_by_code_and_name(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    # đơn 1: gắn khách tên "Nguyễn Văn An"
    async with SessionFactory() as db:
        cust = Customer(tenant_id=octx["owner"]["tenant_id"], full_name="Nguyễn Văn An")
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    o1 = (await _create_order(client, t, _ITEMS, customer_id=cust_id)).json()
    o2 = (await _create_order(client, t, _ITEMS)).json()  # khách lẻ

    # tìm theo mã đơn của o2
    r = await client.get(f"{ORDERS}?q={o2['order_code']}", headers=auth_headers(t))
    assert r.status_code == 200
    assert [o["id"] for o in r.json()["items"]] == [o2["id"]]

    # tìm theo tên khách gần đúng "văn an" (ILIKE, không phân biệt hoa thường)
    r = await client.get(f"{ORDERS}?q=văn an", headers=auth_headers(t))
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == o1["id"]


async def test_board_search_q(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    async with SessionFactory() as db:
        cust = Customer(tenant_id=octx["owner"]["tenant_id"], full_name="Trần Thị Bình")
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    o1 = (await _create_order(client, t, _ITEMS, customer_id=cust_id)).json()
    await _create_order(client, t, _ITEMS)  # khách lẻ

    r = await client.get(f"{ORDERS}/board?q=bình", headers=auth_headers(t))
    assert r.status_code == 200
    ids = [o["id"] for c in r.json()["columns"].values() for o in c]
    assert ids == [o1["id"]]
    assert r.json()["summary"]["total_orders"] == 1


# ── Stage 6.11: search q cũng match SĐT khách (tab Tra cứu) ──────────────────
async def test_list_search_q_by_phone(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    async with SessionFactory() as db:
        cust = Customer(
            tenant_id=octx["owner"]["tenant_id"],
            full_name="Lê Văn Cường",
            phone="0912345678",
        )
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    o1 = (await _create_order(client, t, _ITEMS, customer_id=cust_id)).json()
    await _create_order(client, t, _ITEMS)  # khách lẻ (không SĐT)

    # tìm theo phần SĐT (ILIKE substring)
    r = await client.get(f"{ORDERS}?q=12345", headers=auth_headers(t))
    assert r.status_code == 200
    assert r.json()["total"] == 1
    assert r.json()["items"][0]["id"] == o1["id"]


# ── cancel (soft) — Stage 6.28: lý do bắt buộc + hoàn tiền, sổ luôn cân ──────
async def test_cancel_from_created(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    resp = await _cancel(client, octx["staff_token"], oid, refund=0)
    assert resp.status_code == 200, resp.text
    assert resp.json()["order_status"] == "cancelled"
    assert resp.json()["cancel_reason"] == "Khách đổi ý"
    # Không xóa cứng.
    async with SessionFactory() as db:
        still = await db.scalar(text("SELECT count(*) FROM orders WHERE id=:i"), {"i": oid})
        assert still == 1


async def test_cancel_after_delivered_forbidden(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_delivered(client, t, oid)
    resp = await _cancel(client, t, oid, refund=0)
    assert resp.status_code == 409
    assert resp.json()["code"] == "INVALID_STATUS_TRANSITION"


async def test_cancel_reason_required(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    # thiếu reason → 422 CANCEL_REASON_REQUIRED
    r = await client.post(f"{ORDERS}/{oid}/cancel", json={"refund_amount": 0}, headers=auth_headers(t))
    assert r.status_code == 422
    assert r.json()["code"] == "CANCEL_REASON_REQUIRED"
    # reason chỉ khoảng trắng cũng 422
    r2 = await _cancel(client, t, oid, reason="   ", refund=0)
    assert r2.status_code == 422
    assert r2.json()["code"] == "CANCEL_REASON_REQUIRED"


async def test_cancel_refund_exceeds_paid(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    await _open_shift(client, t)
    oid = await _prepaid_order(client, t)  # đã thu _T_ITEMS
    r = await _cancel(client, t, oid, refund=_T_ITEMS + 1)
    assert r.status_code == 422
    assert r.json()["code"] == "REFUND_EXCEEDS_PAID"


async def test_cancel_unpaid_refund_forbidden(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    await _open_shift(client, t)
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]  # chưa thu
    r = await _cancel(client, t, oid, refund=50000)
    assert r.status_code == 422
    assert r.json()["code"] == "REFUND_EXCEEDS_PAID"  # paid_sum=0


# ── SỔ LUÔN CÂN: doanh thu = tiền thật giữ lại = (đã thu − đã hoàn) ──────────
async def test_cancel_unpaid_book_balanced(client: AsyncClient, octx: dict):
    """Chưa thu, hủy → giữ 0 → doanh thu 0, két không đổi."""
    t = octx["staff_token"]
    sid = await _open_shift(client, t)
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    s0 = await _summary(client, t, sid)
    assert _num(s0["shift_revenue"]) == _T_ITEMS   # trước hủy: doanh thu dự kiến = giá trị đơn
    assert _num(s0["total_collected"]) == 0
    assert (await _cancel(client, t, oid, refund=0)).status_code == 200
    s = await _summary(client, t, sid)
    assert _num(s["shift_revenue"]) == 0           # giữ 0
    assert _num(s["total_collected"]) == 0
    assert _num(s["cash_in_drawer"]) == 0          # két không đổi
    assert _num(s["shift_revenue"]) == _num(s["total_collected"])  # CÂN


async def test_cancel_paid_refund_all_book_balanced(client: AsyncClient, octx: dict):
    """Đã thu T, hoàn tất cả (R=T) → giữ 0 → doanh thu 0, két −T, payment refunded."""
    t = octx["staff_token"]
    sid = await _open_shift(client, t)
    oid = await _prepaid_order(client, t)
    assert _num((await _summary(client, t, sid))["cash_in_drawer"]) == _T_ITEMS
    r = await _cancel(client, t, oid, refund=_T_ITEMS)
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "cancelled"
    assert r.json()["payment_status"] == "refunded"
    assert _num(r.json()["refund_amount"]) == _T_ITEMS
    s = await _summary(client, t, sid)
    assert _num(s["shift_revenue"]) == 0
    assert _num(s["total_collected"]) == 0
    assert _num(s["cash_in_drawer"]) == 0          # két −T
    assert _num(s["shift_revenue"]) == _num(s["total_collected"])


async def test_cancel_paid_refund_partial_book_balanced(client: AsyncClient, octx: dict):
    """Đã thu T, hoàn một phần R → giữ T−R → doanh thu T−R, két −R."""
    t = octx["staff_token"]
    sid = await _open_shift(client, t)
    oid = await _prepaid_order(client, t)
    kept = _T_ITEMS - 40000
    r = await _cancel(client, t, oid, refund=40000)
    assert r.status_code == 200, r.text
    assert _num(r.json()["refund_amount"]) == 40000
    s = await _summary(client, t, sid)
    assert _num(s["shift_revenue"]) == kept        # 70000
    assert _num(s["total_collected"]) == kept
    assert _num(s["cash_in_drawer"]) == kept       # két −40000
    assert _num(s["shift_revenue"]) == _num(s["total_collected"])


async def test_cancel_paid_no_refund_keeps_revenue(client: AsyncClient, octx: dict):
    """Đã thu T, không hoàn (R=0) → giữ T → doanh thu T, két không đổi."""
    t = octx["staff_token"]
    sid = await _open_shift(client, t)
    oid = await _prepaid_order(client, t)
    r = await _cancel(client, t, oid, refund=0)
    assert r.status_code == 200, r.text
    assert r.json()["payment_status"] == "paid"    # không hoàn → vẫn paid
    assert _num(r.json()["refund_amount"]) == 0
    s = await _summary(client, t, sid)
    assert _num(s["shift_revenue"]) == _T_ITEMS    # giữ T
    assert _num(s["total_collected"]) == _T_ITEMS
    assert _num(s["cash_in_drawer"]) == _T_ITEMS   # két không đổi
    assert _num(s["shift_revenue"]) == _num(s["total_collected"])


# ── không sửa total khi đã có payment ───────────────────────────────────────
async def test_cannot_change_total_with_payment(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    sid = await _open_shift(client, octx["staff_token"])
    await _insert_payment(octx, sid, oid, 50000)

    resp = await client.put(f"{ORDERS}/{oid}", json={"total_amount": 999},
                            headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 409
    assert resp.json()["code"] == "ORDER_HAS_PAYMENT"

    # Thêm item cũng bị chặn khi đã có payment.
    add = await client.post(f"{ORDERS}/{oid}/items",
                            json={"service_name": "X", "quantity": 1, "unit_price": 1000},
                            headers=auth_headers(octx["staff_token"]))
    assert add.status_code == 409
    assert add.json()["code"] == "ORDER_HAS_PAYMENT"


async def test_put_notes_and_customer(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    async with SessionFactory() as db:
        cust = Customer(tenant_id=octx["owner"]["tenant_id"], full_name="Chị Lan")
        db.add(cust)
        await db.commit()
        cust_id = str(cust.id)
    resp = await client.put(f"{ORDERS}/{oid}",
                            json={"notes": "Giao gấp", "customer_id": cust_id},
                            headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 200, resp.text
    assert resp.json()["notes"] == "Giao gấp"
    assert resp.json()["customer_id"] == cust_id
    assert resp.json()["customer_name"] == "Chị Lan"  # tên khách nhúng sẵn


# ── items CRUD + recompute ──────────────────────────────────────────────────
async def test_items_crud_recompute_total(client: AsyncClient, octx: dict):
    created = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    oid = created["id"]

    add = await client.post(f"{ORDERS}/{oid}/items",
                            json={"service_name": "Sấy", "quantity": 1, "unit_price": 40000},
                            headers=auth_headers(octx["staff_token"]))
    assert add.status_code == 201, add.text
    assert _num(add.json()["total_amount"]) == 150000  # 110000 + 40000
    item_id = next(i["id"] for i in add.json()["items"] if i["service_name"] == "Sấy")

    upd = await client.put(f"{ORDERS}/{oid}/items/{item_id}",
                           json={"service_name": "Sấy", "quantity": 2, "unit_price": 40000},
                           headers=auth_headers(octx["staff_token"]))
    assert upd.status_code == 200, upd.text
    assert _num(upd.json()["total_amount"]) == 190000  # 110000 + 80000

    dele = await client.delete(f"{ORDERS}/{oid}/items/{item_id}",
                               headers=auth_headers(octx["staff_token"]))
    assert dele.status_code == 200, dele.text
    assert _num(dele.json()["total_amount"]) == 110000


async def test_items_locked_when_ready(client: AsyncClient, octx: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, octx["staff_token"], oid, st)
    resp = await client.post(f"{ORDERS}/{oid}/items",
                             json={"service_name": "X", "quantity": 1, "unit_price": 1000},
                             headers=auth_headers(octx["staff_token"]))
    assert resp.status_code == 409
    assert resp.json()["code"] == "ORDER_ITEMS_LOCKED"


# ── GET by id / code / list ─────────────────────────────────────────────────
async def test_get_by_id_and_code(client: AsyncClient, octx: dict):
    created = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    oid, code = created["id"], created["order_code"]

    by_id = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(octx["staff_token"]))
    assert by_id.status_code == 200 and by_id.json()["id"] == oid

    by_code = await client.get(f"{ORDERS}/code/{code}", headers=auth_headers(octx["staff_token"]))
    assert by_code.status_code == 200 and by_code.json()["id"] == oid


async def test_list_filter_and_pagination(client: AsyncClient, octx: dict):
    o1 = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    await _create_order(client, octx["staff_token"], _ITEMS)
    await _set_status(client, octx["staff_token"], o1["id"], "washing")

    # filter order_status=washing -> chỉ 1.
    f = await client.get(f"{ORDERS}?order_status=washing", headers=auth_headers(octx["staff_token"]))
    assert f.status_code == 200
    assert f.json()["total"] == 1

    # pagination limit.
    p = await client.get(f"{ORDERS}?limit=1", headers=auth_headers(octx["staff_token"]))
    assert p.json()["total"] == 2 and len(p.json()["items"]) == 1


# ── Stage 3.7A: pickup_at (giờ hẹn giao) ────────────────────────────────────
async def _set_order_db(order_id: str, *, pickup_at=None, payment_status=None) -> None:
    async with SessionFactory() as db:
        if pickup_at is not None:
            await db.execute(text("UPDATE orders SET pickup_at=:p WHERE id=:i"),
                             {"p": pickup_at, "i": order_id})
        if payment_status is not None:
            await db.execute(text("UPDATE orders SET payment_status=:s WHERE id=:i"),
                             {"s": payment_status, "i": order_id})
        await db.commit()


async def test_pickup_at_required(client: AsyncClient, octx: dict):
    # Không gửi pickup_at -> 422 (field bắt buộc).
    r = await client.post(ORDERS, json={"items": _ITEMS},
                          headers=auth_headers(octx["staff_token"]))
    assert r.status_code == 422


async def test_pickup_at_in_past_rejected(client: AsyncClient, octx: dict):
    r = await client.post(ORDERS, json={"items": _ITEMS, "pickup_at": _pickup(-1)},
                          headers=auth_headers(octx["staff_token"]))
    assert r.status_code == 422
    assert r.json()["code"] == "PICKUP_AT_IN_PAST"


async def test_order_out_returns_pickup_at(client: AsyncClient, octx: dict):
    body = (await _create_order(client, octx["staff_token"], _ITEMS)).json()
    assert "pickup_at" in body and body["pickup_at"] is not None


async def test_put_pickup_at_edit_and_lock(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    new_pickup = _pickup(10)
    r = await client.put(f"{ORDERS}/{oid}", json={"pickup_at": new_pickup},
                         headers=auth_headers(t))
    assert r.status_code == 200, r.text
    # so sánh theo mốc thời gian (chuẩn hóa khác biệt offset/định dạng).
    assert datetime.fromisoformat(r.json()["pickup_at"]) == datetime.fromisoformat(new_pickup)

    # đơn đã completed -> không sửa được giờ hẹn.
    await _advance_to_delivered(client, t, oid)
    await _set_status(client, t, oid, "completed")
    blocked = await client.put(f"{ORDERS}/{oid}", json={"pickup_at": _pickup(20)},
                               headers=auth_headers(t))
    assert blocked.status_code == 409
    assert blocked.json()["code"] == "ORDER_CLOSED"


# ── Stage B: CHẶN CỨNG giao đơn chưa thu (đai an toàn tầng DB) ──────────────
async def _advance_to_ready(client: AsyncClient, t: str, oid: str) -> None:
    for st in ["washing", "drying", "ready"]:
        await _set_status(client, t, oid, st)


async def test_deliver_unpaid_blocked_409(client: AsyncClient, octx: dict):
    # Đơn unpaid/partial → giao bị CHẶN 409; đơn VẪN ở 'ready' (không set delivered nửa vời).
    t = octx["staff_token"]
    for ps in ["unpaid", "partial"]:
        oid = (await _create_order(client, t, _ITEMS)).json()["id"]
        await _advance_to_ready(client, t, oid)
        if ps == "partial":
            await _set_order_db(oid, payment_status="partial")
        r = await _set_status(client, t, oid, "delivered")
        assert r.status_code == 409, f"{ps}: {r.text}"
        assert r.json()["code"] == "PAYMENT_REQUIRED_BEFORE_DELIVERY"
        # đơn KHÔNG bị set delivered — vẫn 'ready'.
        cur = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(t))
        assert cur.json()["order_status"] == "ready", f"{ps}: đơn không được ở ready"


async def test_deliver_paid_ok(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_ready(client, t, oid)
    await _set_order_db(oid, payment_status="paid")
    r = await _set_status(client, t, oid, "delivered")
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "delivered"


async def test_deliver_debt_ok(client: AsyncClient, octx: dict):
    # Giao-nợ có chủ đích (payment_status='debt') → ĐƯỢC giao (đúng thiết kế).
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_ready(client, t, oid)
    await _set_order_db(oid, payment_status="debt")
    r = await _set_status(client, t, oid, "delivered")
    assert r.status_code == 200, r.text
    assert r.json()["order_status"] == "delivered"


# ── Stage 3.7A: dashboard vận hành (board) ──────────────────────────────────
async def test_board_grouping_overdue_and_summary(client: AsyncClient, octx: dict):
    t = octx["staff_token"]
    o_created = (await _create_order(client, t, _ITEMS)).json()
    o_wash = (await _create_order(client, t, _ITEMS)).json()
    await _set_status(client, t, o_wash["id"], "washing")
    o_overdue = (await _create_order(client, t, _ITEMS)).json()
    o_paid = (await _create_order(client, t, _ITEMS)).json()
    o_debt = (await _create_order(client, t, _ITEMS)).json()
    o_done = (await _create_order(client, t, _ITEMS)).json()
    o_cancel = (await _create_order(client, t, _ITEMS)).json()

    # quá giờ hẹn cho o_overdue; gán payment_status cho o_paid/o_debt.
    past = datetime.now(timezone.utc) - timedelta(hours=2)
    await _set_order_db(o_overdue["id"], pickup_at=past)
    await _set_order_db(o_paid["id"], payment_status="paid")
    await _set_order_db(o_debt["id"], payment_status="debt")
    # o_done -> completed (ẩn khỏi board; Stage B: thu đủ trước khi giao); o_cancel -> cancelled.
    await _advance_to_delivered(client, t, o_done["id"])
    await _set_status(client, t, o_done["id"], "completed")
    await _cancel(client, t, o_cancel["id"], refund=0)

    r = await client.get(f"{ORDERS}/board", headers=auth_headers(t))
    assert r.status_code == 200, r.text
    board = r.json()
    cols = board["columns"]

    # nhóm đúng theo order_status; terminal bị ẩn.
    created_ids = {o["id"] for o in cols["created"]}
    assert created_ids == {o_created["id"], o_overdue["id"], o_paid["id"], o_debt["id"]}
    assert {o["id"] for o in cols["washing"]} == {o_wash["id"]}
    assert cols["drying"] == [] and cols["ready"] == [] and cols["delivered"] == []
    all_ids = {o["id"] for c in cols.values() for o in c}
    assert o_done["id"] not in all_ids and o_cancel["id"] not in all_ids

    # is_overdue: chỉ o_overdue.
    by_id = {o["id"]: o for c in cols.values() for o in c}
    assert by_id[o_overdue["id"]]["is_overdue"] is True
    assert by_id[o_created["id"]]["is_overdue"] is False

    # summary đếm đúng.
    s = board["summary"]
    assert s["total_orders"] == 5
    assert s["unpaid"] == 3   # o_created, o_wash, o_overdue
    assert s["paid"] == 1
    assert s["debt"] == 1
    assert s["overdue"] == 1


async def test_board_delivered_not_overdue(client: AsyncClient, octx: dict):
    # Đơn delivered dù quá giờ hẹn vẫn KHÔNG tính trễ (đã rời tiệm).
    t = octx["staff_token"]
    oid = (await _create_order(client, t, _ITEMS)).json()["id"]
    await _advance_to_delivered(client, t, oid)  # Stage B: thu đủ trước khi giao
    await _set_order_db(oid, pickup_at=datetime.now(timezone.utc) - timedelta(hours=2))

    r = await client.get(f"{ORDERS}/board", headers=auth_headers(t))
    board = r.json()
    delivered = {o["id"]: o for o in board["columns"]["delivered"]}
    assert oid in delivered
    assert delivered[oid]["is_overdue"] is False
    assert board["summary"]["overdue"] == 0


async def test_board_tenant_isolation(client: AsyncClient, octx: dict, owner2: dict):
    await _create_order(client, octx["staff_token"], _ITEMS)
    other = await login(client, owner2["phone"], owner2["password"])
    r = await client.get(f"{ORDERS}/board", headers=auth_headers(other))
    assert r.status_code == 200
    assert r.json()["summary"]["total_orders"] == 0


# ── cách ly tenant ──────────────────────────────────────────────────────────
async def test_cross_tenant_isolation(client: AsyncClient, octx: dict, owner2: dict):
    oid = (await _create_order(client, octx["staff_token"], _ITEMS)).json()["id"]
    other = await login(client, owner2["phone"], owner2["password"])
    got = await client.get(f"{ORDERS}/{oid}", headers=auth_headers(other))
    assert got.status_code == 404
    assert got.json()["code"] == "ORDER_NOT_FOUND"
    lst = await client.get(ORDERS, headers=auth_headers(other))
    assert lst.status_code == 200 and lst.json()["total"] == 0
