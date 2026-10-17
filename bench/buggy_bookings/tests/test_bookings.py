import pytest

from bookings.errors import PaymentDeclined, SoldOut
from bookings.services import bookings, events


def test_booking_reserves_seats_and_charges(conn, user, concert):
    booking_id = bookings.book(conn, user["id"], concert, 2, "tok_visa")
    booking = bookings.get_booking(conn, booking_id)
    assert booking["amount_cents"] == 300000 and booking["status"] == "confirmed"
    assert events.get_event(conn, concert)["booked"] == 2


def test_cannot_book_more_than_capacity(conn, user, concert):
    with pytest.raises(SoldOut):
        bookings.book(conn, user["id"], concert, 11, "tok_visa")
    assert events.get_event(conn, concert)["booked"] == 0


def test_last_seats_can_be_booked(conn, user, concert):
    bookings.book(conn, user["id"], concert, 10, "tok_visa")
    assert events.seats_left(events.get_event(conn, concert)) == 0


def test_declined_payment_does_not_hold_seats(conn, user, concert):
    with pytest.raises(PaymentDeclined):
        bookings.book(conn, user["id"], concert, 2, "declined_card")
    assert events.get_event(conn, concert)["booked"] == 0
    assert bookings.bookings_for_event(conn, concert) == []
