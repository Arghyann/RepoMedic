"""A fake payment gateway. Card tokens starting with 'declined' are rejected."""
import uuid

from bookings.errors import PaymentDeclined


def charge(card_token: str, amount_cents: int) -> str:
    if card_token.startswith("declined"):
        raise PaymentDeclined(f"card {card_token} was declined")
    return f"pay_{uuid.uuid4().hex[:12]}"
