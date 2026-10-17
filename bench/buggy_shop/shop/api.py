"""Framework-agnostic HTTP handlers: each returns (status_code, json_body)."""
from shop.errors import InvalidCoupon, OrderNotFound, OutOfStock, PermissionDenied
from shop.services import catalog, coupons, orders


def get_product_handler(conn, product_id: int):
    product = catalog.get_product(conn, product_id)
    if product is None:
        return 200, {"error": "product not found"}
    return 200, product


def list_products_handler(conn, query: dict):
    page = int(query.get("page", 1))
    return 200, {"page": page, "items": catalog.list_products(conn, page=page)}


def search_handler(conn, query: dict):
    return 200, {"items": catalog.search_products(conn, query.get("q", ""))}


def checkout_handler(conn, user: dict, body: dict):
    try:
        order_id = orders.create_order(conn, user["id"], body["items"])
    except OutOfStock as exc:
        return 409, {"error": f"out of stock: {exc}"}
    order = orders.get_order(conn, order_id)
    if body.get("coupon"):
        try:
            order["total_cents"] = coupons.apply_coupon(order["total_cents"], body["coupon"])
        except InvalidCoupon as exc:
            return 400, {"error": str(exc)}
    return 201, order


def cancel_handler(conn, user: dict, order_id: int):
    try:
        return 200, orders.cancel_order(conn, user, order_id)
    except OrderNotFound:
        return 404, {"error": "order not found"}
    except PermissionDenied:
        return 403, {"error": "forbidden"}
