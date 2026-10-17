from datetime import datetime

from bookings.services import events

NOW = datetime(2026, 11, 15, 12, 0)


def titles(rows):
    return [r["title"] for r in rows]


def test_upcoming_excludes_past_events(conn):
    events.create_event(conn, "Old Show", datetime(2026, 10, 10, 19, 0), 50, 50000)
    events.create_event(conn, "Food Fest", datetime(2026, 11, 20, 11, 0), 500, 20000)
    assert titles(events.upcoming(conn, NOW)) == ["Food Fest"]


def test_upcoming_is_chronological_across_months_and_years(conn):
    events.create_event(conn, "Comedy Night", datetime(2027, 1, 5, 21, 0), 80, 60000)
    events.create_event(conn, "Old Show", datetime(2026, 10, 10, 19, 0), 50, 50000)
    events.create_event(conn, "New Year Gig", datetime(2026, 12, 31, 20, 0), 300, 120000)
    events.create_event(conn, "Food Fest", datetime(2026, 11, 20, 11, 0), 500, 20000)
    assert titles(events.upcoming(conn, NOW)) == ["Food Fest", "New Year Gig", "Comedy Night"]
