from bookings import api


def test_signup_conflict_returns_409(conn):
    assert api.signup_handler(conn, {"email": "dev@example.com", "name": "Dev"})[0] == 201
    assert api.signup_handler(conn, {"email": "dev@example.com", "name": "Dev"})[0] == 409


def test_book_handler_maps_declined_payment_to_402(conn, user, concert):
    status, _ = api.book_handler(conn, user, {"event_id": concert, "quantity": 1, "card_token": "declined_x"})
    assert status == 402


def test_book_handler_unknown_event_404(conn, user):
    status, _ = api.book_handler(conn, user, {"event_id": 999, "quantity": 1, "card_token": "tok_visa"})
    assert status == 404
