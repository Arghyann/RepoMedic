import pytest

from shop.errors import OutOfStock
from shop.services import catalog


def test_get_product(conn):
    assert catalog.get_product(conn, 1)["name"] == "Product 01"
    assert catalog.get_product(conn, 999) is None


def test_first_page_starts_at_first_product(conn):
    page = catalog.list_products(conn, page=1, page_size=10)
    assert [p["id"] for p in page] == list(range(1, 11))


def test_last_page_is_partial(conn):
    page = catalog.list_products(conn, page=3, page_size=10)
    assert [p["id"] for p in page] == list(range(21, 27))


def test_search_finds_substring(conn):
    names = [p["name"] for p in catalog.search_products(conn, "Product 1")]
    assert "Product 10" in names and "Product 01" not in names


def test_search_is_not_injectable(conn):
    assert catalog.search_products(conn, "' OR '1'='1") == []


def test_search_handles_quotes(conn):
    results = catalog.search_products(conn, "O'Brien")
    assert [p["name"] for p in results] == ["O'Brien Coffee Mug"]


def test_reserve_stock_decrements(conn):
    catalog.reserve_stock(conn, 1, 2)
    assert catalog.get_product(conn, 1)["stock"] == 3


def test_reserve_stock_rejects_oversell(conn):
    with pytest.raises(OutOfStock):
        catalog.reserve_stock(conn, 1, 6)
    assert catalog.get_product(conn, 1)["stock"] == 5
