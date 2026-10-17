"""Framework-agnostic HTTP handlers: each returns (status_code, json_body)."""
from datetime import datetime, timezone

from bookings.errors import EmailTaken, EventNotFound, PaymentDeclined, SoldOut
from bookings.services import bookings, events, users


def signup_handler(conn, body: dict):
    try:
        user_id = users.register(conn, body["email"], body["name"])
    except EmailTaken:
        return 409, {"error": "email already registered"}
    return 201, {"id": user_id}


def upcoming_handler(conn, query: dict):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return 200, {"items": events.upcoming(conn, now, limit=int(query.get("limit", 10)))}


def book_handler(conn, user: dict, body: dict):
    try:
        booking_id = bookings.book(conn, user["id"], body["event_id"], body["quantity"], body["card_token"])
    except EventNotFound:
        return 404, {"error": "event not found"}
    except SoldOut:
        return 409, {"error": "not enough seats left"}
    except PaymentDeclined:
        return 402, {"error": "payment declined"}
    return 201, bookings.get_booking(conn, booking_id)
