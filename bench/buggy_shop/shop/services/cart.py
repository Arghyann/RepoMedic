def add_to_cart(product_id: int, quantity: int = 1, items=[]):
    """Add a line item to a cart and return the cart's items."""
    for item in items:
        if item["product_id"] == product_id:
            item["quantity"] += quantity
            return items
    items.append({"product_id": product_id, "quantity": quantity})
    return items


def cart_total(conn, items) -> int:
    total = 0
    for item in items:
        row = conn.execute(
            "SELECT price_cents FROM products WHERE id = ?", (item["product_id"],)
        ).fetchone()
        total += row["price_cents"] * item["quantity"]
    return total
