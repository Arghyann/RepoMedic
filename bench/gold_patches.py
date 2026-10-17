"""Reference ("gold") fixes for every benchmark case, like SWE-bench's gold patches.

They are never shown to the agent: the harness copies only the patient repo. They exist so
`tests/test_bench_cases.py` can prove each case is valid: the bug really breaks the judging
tests, and a correct fix makes exactly those tests pass without breaking anything else.

Format: case_id -> list of (path, search, replace) edits.
"""

GOLD = {
    # ---------------------------------------------------------------- buggy_shop (main suite)
    "pagination-off-by-one": [
        ("shop/services/catalog.py",
         "    offset = page * page_size\n",
         "    offset = (page - 1) * page_size\n"),
    ],
    "sql-injection-search": [
        ("shop/services/catalog.py",
         '    query = f"SELECT * FROM products WHERE name LIKE \'%{term}%\' ORDER BY id"\n'
         "    return [dict(r) for r in conn.execute(query).fetchall()]\n",
         '    query = "SELECT * FROM products WHERE name LIKE ? ORDER BY id"\n'
         '    return [dict(r) for r in conn.execute(query, (f"%{term}%",)).fetchall()]\n'),
    ],
    "mutable-default-cart": [
        ("shop/services/cart.py",
         "def add_to_cart(product_id: int, quantity: int = 1, items=[]):\n"
         '    """Add a line item to a cart and return the cart\'s items."""\n',
         "def add_to_cart(product_id: int, quantity: int = 1, items=None):\n"
         '    """Add a line item to a cart and return the cart\'s items."""\n'
         "    if items is None:\n"
         "        items = []\n"),
    ],
    "naive-datetime-coupon": [
        ("shop/services/coupons.py",
         "    now = now or datetime.now()\n",
         "    now = now or datetime.now(timezone.utc)\n"),
    ],
    "idor-cancel-order": [
        ("shop/services/orders.py",
         "        raise OrderNotFound(order_id)\n"
         "    conn.execute(\"UPDATE orders SET status = 'cancelled' WHERE id = ?\", (order_id,))\n",
         "        raise OrderNotFound(order_id)\n"
         '    if order["user_id"] != user["id"] and not user.get("is_admin"):\n'
         "        raise PermissionDenied(order_id)\n"
         "    conn.execute(\"UPDATE orders SET status = 'cancelled' WHERE id = ?\", (order_id,))\n"),
    ],
    "oversell-stock": [
        ("shop/services/catalog.py",
         "        raise ProductNotFound(product_id)\n"
         "    conn.execute(\n"
         '        "UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id)\n',
         "        raise ProductNotFound(product_id)\n"
         '    if row["stock"] < quantity:\n'
         "        raise OutOfStock(product_id)\n"
         "    conn.execute(\n"
         '        "UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id)\n'),
    ],
    "missing-404": [
        ("shop/api.py",
         '        return 200, {"error": "product not found"}\n',
         '        return 404, {"error": "product not found"}\n'),
    ],
    # ---------------------------------------------------------------- buggy_bookings (held-out suite)
    "email-case-duplicates": [
        ("bookings/services/users.py",
         '    """Create a user account. Each email address may only be registered once."""\n',
         '    """Create a user account. Each email address may only be registered once."""\n'
         "    email = email.strip().lower()\n"),
    ],
    "declined-payment-holds-seats": [
        ("bookings/services/bookings.py",
         '    conn.execute("UPDATE events SET booked = booked + ? WHERE id = ?", (quantity, event_id))\n'
         "    conn.commit()\n"
         "\n"
         '    amount = quantity * event["price_cents"]\n'
         "    payment_id = payments.charge(card_token, amount)\n",
         '    amount = quantity * event["price_cents"]\n'
         "    payment_id = payments.charge(card_token, amount)\n"
         "\n"
         '    conn.execute("UPDATE events SET booked = booked + ? WHERE id = ?", (quantity, event_id))\n'),
    ],
    "upcoming-events-date-order": [
        ("bookings/services/events.py",
         "    now_str = now.strftime(DATE_FORMAT)\n"
         "    rows = conn.execute(\n"
         '        "SELECT * FROM events WHERE starts_at > ? ORDER BY starts_at LIMIT ?", (now_str, limit)\n'
         "    ).fetchall()\n"
         "    return [dict(r) for r in rows]\n",
         '    rows = [dict(r) for r in conn.execute("SELECT * FROM events").fetchall()]\n'
         '    future = [r for r in rows if datetime.strptime(r["starts_at"], DATE_FORMAT) > now]\n'
         '    future.sort(key=lambda r: datetime.strptime(r["starts_at"], DATE_FORMAT))\n'
         "    return future[:limit]\n"),
    ],
}
