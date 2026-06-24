"""Schemas cho trang tracking CÔNG KHAI (GET /public/track/{order_code}).

CHỈ field an toàn cho người lạ: trạng thái + timeline + liên hệ chi nhánh.
TUYỆT ĐỐI KHÔNG có: tiền (total/paid/amount), payment_status, tên/SĐT khách,
tenant_id/branch_id nội bộ.
"""
from datetime import datetime

from pydantic import BaseModel


class PublicTimelineItem(BaseModel):
    status: str
    at: datetime


class PublicBranchContact(BaseModel):
    name: str
    address: str | None = None
    phone: str | None = None


class PublicTrackOut(BaseModel):
    order_code: str
    order_status: str  # raw (created/washing/…) — giữ cho client cần chi tiết
    status_group: str  # gom nhóm: processing | ready | delivered
    status_label: str  # nhãn khách: "Đang xử lý" | "Đã xong — mời lấy" | "Đã giao"
    tenant_name: str  # tên tiệm — header + footer track-site (KHÔNG lộ id)
    pickup_at: datetime
    branch: PublicBranchContact
    timeline: list[PublicTimelineItem]
