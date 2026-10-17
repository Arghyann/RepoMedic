class BookingError(Exception):
    """Base error for the bookings domain."""


class EventNotFound(BookingError):
    pass


class SoldOut(BookingError):
    pass


class PaymentDeclined(BookingError):
    pass


class EmailTaken(BookingError):
    pass
