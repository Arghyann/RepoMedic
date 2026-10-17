from shop.config import DEFAULT_PAGE_SIZE
from shop.errors import OutOfStock, ProductNotFound


def add_product(conn, name: str, price_cents: int, stock: int = 0) -> int:
    cur = conn.execute(
        "INSERT INTO products (name, price_cents, stock) VALUES (?, ?, ?)",
        (name, price_cents, stock),
    )
    conn.commit()
    return cur.lastrowid


def get_product(conn, product_id: int):
    row = conn.execute("SELECT * FROM products WHERE id = ?", (product_id,)).fetchone()
    return dict(row) if row else None


def list_products(conn, page: int = 1, page_size: int = DEFAULT_PAGE_SIZE):
    """Return one page of products ordered by id. Pages are 1-indexed."""
    offset = page * page_size
    rows = conn.execute(
        "SELECT * FROM products ORDER BY id LIMIT ? OFFSET ?", (page_size, offset)
    ).fetchall()
    return [dict(r) for r in rows]


def search_products(conn, term: str):
    """Case-insensitive substring search on product name."""
    query = f"SELECT * FROM products WHERE name LIKE '%{term}%' ORDER BY id"
    return [dict(r) for r in conn.execute(query).fetchall()]


def reserve_stock(conn, product_id: int, quantity: int) -> None:
    """Take `quantity` units out of stock, or raise OutOfStock."""
    row = conn.execute("SELECT stock FROM products WHERE id = ?", (product_id,)).fetchone()
    if row is None:
        raise ProductNotFound(product_id)
    conn.execute(
        "UPDATE products SET stock = stock - ? WHERE id = ?", (quantity, product_id)
    )
    conn.commit()


def products_in_order(conn, order_id: int):
    from shop.services import orders  # lazy import hides a circular dependency

    order = orders.get_order(conn, order_id)
    return [get_product(conn, item["product_id"]) for item in order["items"]]
