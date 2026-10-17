from bookings.errors import EventNotFound, SoldOut
from bookings.services import payments
from bookings.services.events import get_event, seats_left


def book(conn, user_id: int, event_id: int, quantity: int, card_token: str) -> int:
    """Reserve seats, take payment and create a confirmed booking."""
    event = get_event(conn, event_id)
    if event is None:
        raise EventNotFound(event_id)
    if quantity > seats_left(event):
        raise SoldOut(event_id)

    conn.execute("UPDATE events SET booked = booked + ? WHERE id = ?", (quantity, event_id))
    conn.commit()

    amount = quantity * event["price_cents"]
    payment_id = payments.charge(card_token, amount)

    cur = conn.execute(
        "INSERT INTO bookings (user_id, event_id, quantity, amount_cents, payment_id) VALUES (?, ?, ?, ?, ?)",
        (user_id, event_id, quantity, amount, payment_id),
    )
    conn.commit()
    return cur.lastrowid


def get_booking(conn, booking_id: int):
    row = conn.execute("SELECT * FROM bookings WHERE id = ?", (booking_id,)).fetchone()
    return dict(row) if row else None


def bookings_for_event(conn, event_id: int):
    rows = conn.execute("SELECT * FROM bookings WHERE event_id = ?", (event_id,)).fetchall()
    return [dict(r) for r in rows]
