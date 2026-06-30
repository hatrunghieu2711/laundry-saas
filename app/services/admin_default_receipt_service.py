"""Mẫu in MẶC ĐỊNH system-wide (Super Admin).

Lưu app_settings key='default_receipt' (NGOÀI RLS → admin GUC rỗng đọc/ghi được).
⚠️ KHÁC receipt_default_config (mẫu mặc định PER-TENANT, Stage 5.10) — đừng nhầm.

Mẫu chuẩn = phần CHUNG: blocks + bilingual + track_base_url. KHÔNG branch_contact_blocks
(per-branch, key=branch_id) / logo_url (per-tenant) / auto_print (cột riêng). Tạo tenant
mới COPY mẫu này vào receipt_config; tenant tự sửa sau (không liên kết ngược).
"""
import copy
from typing import Any

from sqlalchemy import func
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.app_settings import AppSettings
from app.schemas.settings import ReceiptUpdate
from app.services import settings_service

_KEY = "default_receipt"


def _merge_required_blocks(receipt: dict[str, Any]) -> dict[str, Any]:
    """MERGE-ON-READ cho MẪU DEFAULT: chèn khối hệ thống BẮT BUỘC còn THIẾU.

    Bắt buộc = khối trong _default_blocks() có ``removable is False`` (GENERIC —
    hiện chỉ payment_status, sau này thêm khối removable:false nào cũng tự áp,
    KHÔNG hardcode). So theo ``type``:
    - Đã có (idempotent) → bỏ qua, KHÔNG nhân đôi.
    - Thiếu → MỞ 1 HÀNG MỚI ngay sau khối NEO (khối đứng trước nó trong _default
      mà mẫu đang có, gần nhất) bằng cách dời ``row`` các khối phía sau +1, rồi
      đặt khối bắt buộc vào hàng trống đó (giữ nguyên content seed trilingual).
      Không thấy neo → chèn CUỐI (row lớn nhất +1).

    ⚠️ CHỈ dùng cho mẫu DEFAULT (app_settings 'default_receipt') + tenant TẠO MỚI.
    KHÔNG đụng tenant receipt_config hiện có (Bill render THEO `row`, nên không
    đổi/xóa khối đang có — chỉ thêm). Bản sao mới (không mutate `receipt` đầu vào).
    """
    blocks = [dict(b) for b in (receipt.get("blocks") or [])]
    defaults = settings_service._default_blocks()
    for idx, req in enumerate(defaults):
        if req.get("removable") is not False:
            continue  # chỉ khối hệ thống bắt buộc (removable:false)
        if any(b.get("type") == req["type"] for b in blocks):
            continue  # đã có → idempotent
        # Neo = khối đứng TRƯỚC req trong _default mà mẫu đang có (gần nhất).
        anchor_row = None
        for prev in reversed(defaults[:idx]):
            rows = [b.get("row", 0) for b in blocks if b.get("type") == prev["type"]]
            if rows:
                anchor_row = max(rows)
                break
        if anchor_row is None:  # không thấy neo → cuối bill
            anchor_row = max((b.get("row", 0) for b in blocks), default=-1)
        for b in blocks:  # mở hàng trống ngay sau neo
            if b.get("row", 0) > anchor_row:
                b["row"] = b.get("row", 0) + 1
        nb = copy.deepcopy(req)
        nb["row"] = anchor_row + 1
        nb["col"] = "full"  # khối bắt buộc đứng riêng 1 hàng
        blocks.append(nb)
    return {**receipt, "blocks": blocks}


async def get_stored_default_receipt(db: AsyncSession) -> dict[str, Any] | None:
    """Mẫu chuẩn ĐÃ lưu RAW (None nếu admin CHƯA set). create_tenant copy (rồi merge)."""
    row = await db.get(AppSettings, _KEY)
    return row.value if row is not None else None


async def get_default_receipt(db: AsyncSession) -> dict[str, Any]:
    """GET endpoint: chưa set → _default_receipt() (placeholder). MERGE khối hệ thống
    bắt buộc còn thiếu (mẫu lưu trước khi thêm payment_status → tự bổ sung khi đọc)."""
    stored = await get_stored_default_receipt(db)
    base = stored if stored is not None else settings_service._default_receipt()
    return _merge_required_blocks(base)


async def set_default_receipt(db: AsyncSession, data: ReceiptUpdate) -> dict[str, Any]:
    """Validate (ReceiptUpdate đã ép logo_url='') + STRIP branch_contact_blocks={} →
    chỉ giữ phần CHUNG. Upsert app_settings key='default_receipt' (ngoài RLS)."""
    payload = data.model_dump(mode="json")
    payload["branch_contact_blocks"] = {}  # mẫu chuẩn KHÔNG chứa liên hệ per-CN
    payload["logo_url"] = ""                # logo per-tenant (ReceiptUpdate đã ép "")
    stmt = (
        pg_insert(AppSettings)
        .values(key=_KEY, value=payload)
        .on_conflict_do_update(
            index_elements=["key"],
            set_={"value": payload, "updated_at": func.now()},
        )
    )
    await db.execute(stmt)
    await db.commit()
    return payload
