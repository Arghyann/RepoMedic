from datetime import datetime, timezone

from shop.errors import InvalidCoupon

COUPONS = {
    "WELCOME10": {"percent": 10, "expires_at": datetime(2099, 1, 1, tzinfo=timezone.utc)},
    "SUMMER21": {"percent": 20, "expires_at": datetime(2021, 9, 1, tzinfo=timezone.utc)},
}


def apply_coupon(total_cents: int, code: str, now: datetime | None = None) -> int:
    """Return the discounted total. Raises InvalidCoupon for unknown/expired codes."""
    coupon = COUPONS.get(code.upper())
    if coupon is None:
        raise InvalidCoupon(code)
    now = now or datetime.now()
    if coupon["expires_at"] < now:
        raise InvalidCoupon(f"{code} expired")
    return total_cents - total_cents * coupon["percent"] // 100
