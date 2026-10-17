from datetime import datetime, timezone

import pytest

from shop.errors import InvalidCoupon
from shop.services.coupons import apply_coupon


def test_valid_coupon_applies_discount():
    assert apply_coupon(1000, "WELCOME10") == 900


def test_expired_coupon_rejected_with_explicit_clock():
    with pytest.raises(InvalidCoupon):
        apply_coupon(1000, "SUMMER21", now=datetime(2024, 1, 1, tzinfo=timezone.utc))


def test_unknown_coupon_rejected():
    with pytest.raises(InvalidCoupon):
        apply_coupon(1000, "NOPE")
