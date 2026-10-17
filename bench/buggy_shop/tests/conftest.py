import pytest

from shop.db import connect
from shop.services import auth, catalog


@pytest.fixture
def conn():
    c = connect(":memory:")
    for i in range(1, 26):
        catalog.add_product(c, f"Product {i:02d}", price_cents=100 * i, stock=5)
    catalog.add_product(c, "O'Brien Coffee Mug", price_cents=1500, stock=3)
    yield c
    c.close()


@pytest.fixture
def users(conn):
    alice = auth.register(conn, "alice@example.com", "alice-pw")
    bob = auth.register(conn, "bob@example.com", "bob-pw")
    admin = auth.register(conn, "admin@example.com", "admin-pw", is_admin=True)
    return {
        "alice": auth.get_user(conn, alice),
        "bob": auth.get_user(conn, bob),
        "admin": auth.get_user(conn, admin),
    }
