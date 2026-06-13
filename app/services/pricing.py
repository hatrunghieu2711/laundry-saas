"""Tính tiền một dòng đơn từ bảng giá dịch vụ (service).

Trả về (snapshot_name, unit_price, subtotal) — order_items LƯU 3 giá trị này làm
snapshot, không phụ thuộc bảng giá sau này.

- per_unit: subtotal = quantity × service.unit_price.
- tier: chọn bậc đầu tiên có max_value >= quantity (đã sort tăng dần);
  bậc trọn gói (per_unit=false) -> subtotal = price (KHÔNG nhân theo lượng);
  bậc overflow max_value=NULL (per_unit=true) -> subtotal = price × quantity.
"""
from decimal import ROUND_HALF_UP, Decimal

from app.core.errors import APIError
from app.models.service import Service, ServiceTier


def _round(value: Decimal) -> Decimal:
    """VND không số lẻ -> số nguyên (round half up)."""
    return value.quantize(Decimal(1), rounding=ROUND_HALF_UP)


def _tier_line(service: Service, tier: ServiceTier, quantity: Decimal) -> tuple[str, Decimal, Decimal]:
    name = f"{service.name} ({tier.label})"
    if tier.per_unit:
        return name, tier.price, _round(quantity * tier.price)
    return name, tier.price, tier.price  # trọn gói


def price_line(service: Service, quantity: Decimal) -> tuple[str, Decimal, Decimal]:
    if service.pricing_type == "per_unit":
        return service.name, service.unit_price, _round(quantity * service.unit_price)

    # tier: sort theo ngưỡng tăng dần, bậc overflow (max_value=NULL) xuống cuối.
    tiers = sorted(
        service.tiers, key=lambda t: (t.max_value is None, t.max_value or Decimal(0))
    )
    for tier in tiers:
        if tier.max_value is not None and quantity <= tier.max_value:
            return _tier_line(service, tier, quantity)
    overflow = next((t for t in tiers if t.max_value is None), None)
    if overflow is None:
        raise APIError(
            422, "NO_MATCHING_TIER", "Không có bậc giá phù hợp cho khối lượng này"
        )
    return _tier_line(service, overflow, quantity)
