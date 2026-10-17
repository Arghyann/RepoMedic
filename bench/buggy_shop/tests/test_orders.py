import pytest

from shop.errors import PermissionDenied
from shop.services import auth, catalog, orders


def test_create_order_totals_and_reserves(conn, users):
    order_id = orders.create_order(
        conn, users["alice"]["id"], [{"product_id": 2, "quantity": 2}]
    )
    order = orders.get_order(conn, order_id)
    assert order["total_cents"] == 400
    assert catalog.get_product(conn, 2)["stock"] == 3


def test_owner_can_cancel(conn, users):
    order_id = orders.create_order(conn, users["alice"]["id"], [{"product_id": 1, "quantity": 1}])
    assert orders.cancel_order(conn, users["alice"], order_id)["status"] == "cancelled"


def test_admin_can_cancel_any_order(conn, users):
    order_id = orders.create_order(conn, users["alice"]["id"], [{"product_id": 1, "quantity": 1}])
    assert orders.cancel_order(conn, users["admin"], order_id)["status"] == "cancelled"


def test_other_user_cannot_cancel_order(conn, users):
    order_id = orders.create_order(conn, users["alice"]["id"], [{"product_id": 1, "quantity": 1}])
    with pytest.raises(PermissionDenied):
        orders.cancel_order(conn, users["bob"], order_id)
    assert orders.get_order(conn, order_id)["status"] == "pending"


def test_password_roundtrip(conn):
    uid = auth.register(conn, "carol@example.com", "s3cret")
    user = auth.get_user(conn, uid)
    assert auth.verify_password("s3cret", user["password_hash"])
    assert not auth.verify_password("wrong", user["password_hash"])
