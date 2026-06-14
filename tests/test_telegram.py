"""Test Telegram thông báo đóng ca.

- Unit: build_shift_close_message (lệch ít → không ⚠️, lệch nhiều → có ⚠️).
- Integration: đóng ca gọi send_message với chat_id/message đúng (mock httpx-layer).
- Lỗi gửi KHÔNG làm fail đóng ca.
"""
from datetime import datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest_asyncio
from httpx import AsyncClient

from app.core.database import SessionFactory
from app.models.tenant_settings import TenantSettings
from app.services import telegram_service
from tests.conftest import auth_headers, login


def _fake_shift(cash_difference: int, *, income: int = 0, expense: int = 0) -> SimpleNamespace:
    return SimpleNamespace(
        opening_cash=Decimal(500000),
        total_cash=Decimal(300000),
        total_transfer=Decimal(150000),
        total_qr=Decimal(50000),
        total_cod=Decimal(0),
        total_income=Decimal(income),
        total_expense=Decimal(expense),
        orders_count=7,
        closing_cash_expected=Decimal(800000),
        closing_cash_actual=Decimal(800000 + cash_difference),
        cash_difference=Decimal(cash_difference),
        closed_at=datetime(2026, 6, 13, 17, 30, tzinfo=timezone.utc),
    )


# ── unit: build message ─────────────────────────────────────────────────────
def test_message_small_diff_no_warning():
    msg = telegram_service.build_shift_close_message(
        branch_name="CN Trung Tâm", closed_by_name="Nguyễn Văn A",
        shift=_fake_shift(10000), threshold=Decimal(50000),
    )
    assert "CN Trung Tâm" in msg
    assert "Nguyễn Văn A" in msg
    assert "300.000đ" in msg          # total_cash
    assert "Lệch két: +10.000đ" in msg
    assert "⚠️" not in msg             # 10000 <= 50000


def test_message_large_diff_has_warning():
    msg = telegram_service.build_shift_close_message(
        branch_name="CN A", closed_by_name="B",
        shift=_fake_shift(-120000), threshold=Decimal(50000),
    )
    assert "⚠️" in msg
    assert "LỆCH KÉT" in msg
    assert "Lệch két: -120.000đ" in msg


def test_message_shows_income_expense_when_present():
    msg = telegram_service.build_shift_close_message(
        branch_name="CN A", closed_by_name="B",
        shift=_fake_shift(0, income=80000, expense=30000), threshold=Decimal(50000),
    )
    assert "Thu khác (tiền mặt): 80.000đ" in msg
    assert "Chi (tiền mặt): 30.000đ" in msg


def test_message_hides_income_expense_when_zero():
    msg = telegram_service.build_shift_close_message(
        branch_name="CN A", closed_by_name="B",
        shift=_fake_shift(0), threshold=Decimal(50000),
    )
    assert "Thu khác (tiền mặt)" not in msg
    assert "Chi (tiền mặt)" not in msg


# ── integration fixtures ────────────────────────────────────────────────────
@pytest_asyncio.fixture
async def tctx(client: AsyncClient, owner: dict) -> dict:
    """Owner + branch + staff, và bật cấu hình Telegram cho tenant."""
    owner_token = await login(client, owner["phone"], owner["password"])
    branch = (await client.post("/api/v1/branches", json={"name": "CN A"},
                                headers=auth_headers(owner_token))).json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV A", "phone": "0900000061", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    async with SessionFactory() as db:
        db.add(TenantSettings(
            tenant_id=owner["tenant_id"],
            telegram_bot_token="test-bot-token",
            telegram_owner_chat_id="123456",
            cash_diff_threshold=Decimal(50000),
        ))
        await db.commit()
    return {
        "owner": owner,
        "staff_token": await login(client, "0900000061", "pass123"),
        "branch": branch,
    }


async def _open_close(client, token, *, opening, actual) -> dict:
    opened = await client.post("/api/v1/shifts/open", json={"opening_cash": opening},
                               headers=auth_headers(token))
    sid = opened.json()["id"]
    return await client.post(f"/api/v1/shifts/{sid}/close",
                             json={"closing_cash_actual": actual},
                             headers=auth_headers(token))


# ── integration: gửi đúng ────────────────────────────────────────────────────
async def test_close_sends_telegram(client: AsyncClient, tctx: dict, monkeypatch):
    sent = []

    async def fake_send(bot_token, chat_id, text):
        sent.append({"token": bot_token, "chat_id": chat_id, "text": text})

    monkeypatch.setattr(telegram_service, "send_message", fake_send)

    # opening 0, không payment -> expected 0; actual 0 -> lệch 0 (không ⚠️).
    resp = await _open_close(client, tctx["staff_token"], opening=0, actual=0)
    assert resp.status_code == 200, resp.text

    assert len(sent) == 1
    assert sent[0]["token"] == "test-bot-token"
    assert sent[0]["chat_id"] == "123456"
    assert "ĐÓNG CA" in sent[0]["text"]
    assert "CN A" in sent[0]["text"]
    assert "⚠️" not in sent[0]["text"]


async def test_close_large_diff_warns(client: AsyncClient, tctx: dict, monkeypatch):
    sent = []

    async def fake_send(bot_token, chat_id, text):
        sent.append(text)

    monkeypatch.setattr(telegram_service, "send_message", fake_send)

    # expected 0, actual 200000 -> lệch 200000 > 50000 -> ⚠️.
    resp = await _open_close(client, tctx["staff_token"], opening=0, actual=200000)
    assert resp.status_code == 200
    assert len(sent) == 1
    assert "⚠️" in sent[0]


async def test_send_failure_does_not_fail_close(client: AsyncClient, tctx: dict, monkeypatch):
    async def boom(bot_token, chat_id, text):
        raise RuntimeError("telegram down")

    monkeypatch.setattr(telegram_service, "send_message", boom)

    resp = await _open_close(client, tctx["staff_token"], opening=0, actual=0)
    # Đóng ca vẫn thành công dù gửi Telegram lỗi.
    assert resp.status_code == 200
    assert resp.json()["status"] == "closed"


async def test_no_settings_no_send(client: AsyncClient, owner: dict, monkeypatch):
    """Tenant chưa cấu hình Telegram -> không gửi, đóng ca vẫn ok."""
    sent = []

    async def fake_send(bot_token, chat_id, text):
        sent.append(text)

    monkeypatch.setattr(telegram_service, "send_message", fake_send)

    owner_token = await login(client, owner["phone"], owner["password"])
    branch = (await client.post("/api/v1/branches", json={"name": "CN X"},
                                headers=auth_headers(owner_token))).json()
    await client.post(
        "/api/v1/users",
        json={"full_name": "NV", "phone": "0900000062", "password": "pass123",
              "role": "staff", "branch_id": branch["id"]},
        headers=auth_headers(owner_token),
    )
    staff = await login(client, "0900000062", "pass123")
    resp = await _open_close(client, staff, opening=0, actual=0)
    assert resp.status_code == 200
    assert sent == []
