import pytest

from bookings.errors import EmailTaken
from bookings.services import users


def test_register_and_find(conn):
    uid = users.register(conn, "bob@example.com", "Bob")
    assert users.find_by_email(conn, "bob@example.com")["id"] == uid


def test_duplicate_email_rejected(conn):
    users.register(conn, "bob@example.com", "Bob")
    with pytest.raises(EmailTaken):
        users.register(conn, "bob@example.com", "Bobby")


def test_email_uniqueness_ignores_case_and_spaces(conn):
    users.register(conn, "Alice@Example.com", "Alice")
    with pytest.raises(EmailTaken):
        users.register(conn, "  alice@example.COM ", "Imposter")
