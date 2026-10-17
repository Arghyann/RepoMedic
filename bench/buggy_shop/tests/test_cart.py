from shop.services.cart import add_to_cart, cart_total


def test_add_to_cart_merges_quantities():
    items = add_to_cart(1, 1, items=[])
    items = add_to_cart(1, 2, items=items)
    assert items == [{"product_id": 1, "quantity": 3}]


def test_new_carts_do_not_share_items():
    alice_cart = add_to_cart(1)
    bob_cart = add_to_cart(2)
    assert bob_cart == [{"product_id": 2, "quantity": 1}]
    assert alice_cart is not bob_cart


def test_cart_total(conn):
    items = [{"product_id": 1, "quantity": 2}, {"product_id": 3, "quantity": 1}]
    assert cart_total(conn, items) == 2 * 100 + 300
