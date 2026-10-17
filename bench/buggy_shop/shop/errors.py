class ShopError(Exception):
    """Base error for the shop domain."""


class ProductNotFound(ShopError):
    pass


class OrderNotFound(ShopError):
    pass


class OutOfStock(ShopError):
    pass


class InvalidCoupon(ShopError):
    pass


class PermissionDenied(ShopError):
    pass
