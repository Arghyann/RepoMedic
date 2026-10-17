from shop import api


def test_get_product_ok(conn):
    status, body = api.get_product_handler(conn, 1)
    assert status == 200 and body["id"] == 1


def test_missing_product_returns_404(conn):
    status, body = api.get_product_handler(conn, 999)
    assert status == 404
    assert "error" in body


def test_checkout_creates_order(conn, users):
    status, body = api.checkout_handler(
        conn, users["alice"], {"items": [{"product_id": 1, "quantity": 1}]}
    )
    assert status == 201 and body["total_cents"] == 100
