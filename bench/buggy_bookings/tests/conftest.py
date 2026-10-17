from datetime import datetime

import pytest

from bookings.db import connect
from bookings.services import events, users


@pytest.fixture
def conn():
    c = connect(":memory:")
    yield c
    c.close()


@pytest.fixture
def user(conn):
    return {"id": users.register(conn, "riya@example.com", "Riya")}


@pytest.fixture
def concert(conn):
    return events.create_event(conn, "Arijit Live", datetime(2026, 12, 20, 19, 30), capacity=10, price_cents=150000)
