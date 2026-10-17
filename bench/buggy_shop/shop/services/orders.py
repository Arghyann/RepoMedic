from shop.errors import OrderNotFound, PermissionDenied, ProductNotFound
from shop.services.catalog import reserve_stock


def create_order(conn, user_id: int, items) -> int:
    total = 0
    for item in items:
        product = conn.execute(
            "SELECT * FROM products WHERE id = ?", (item["product_id"],)
        ).fetchone()
        if product is None:
            raise ProductNotFound(item["product_id"])
        reserve_stock(conn, item["product_id"], item["quantity"])
        total += product["price_cents"] * item["quantity"]

    cur = conn.execute(
        "INSERT INTO orders (user_id, total_cents) VALUES (?, ?)", (user_id, total)
    )
    order_id = cur.lastrowid
    for item in items:
        conn.execute(
            "INSERT INTO order_items (order_id, product_id, quantity) VALUES (?, ?, ?)",
            (order_id, item["product_id"], item["quantity"]),
        )
    conn.commit()
    return order_id


def get_order(conn, order_id: int):
    row = conn.execute("SELECT * FROM orders WHERE id = ?", (order_id,)).fetchone()
    if row is None:
        return None
    order = dict(row)
    order["items"] = [
        dict(r)
        for r in conn.execute(
            "SELECT product_id, quantity FROM order_items WHERE order_id = ?", (order_id,)
        ).fetchall()
    ]
    return order


def cancel_order(conn, user: dict, order_id: int) -> dict:
    """Cancel an order. Only the order's owner or an admin may cancel it."""
    order = get_order(conn, order_id)
    if order is None:
        raise OrderNotFound(order_id)
    conn.execute("UPDATE orders SET status = 'cancelled' WHERE id = ?", (order_id,))
    conn.commit()
    return get_order(conn, order_id)
