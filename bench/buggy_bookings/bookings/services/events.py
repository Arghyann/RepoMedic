from datetime import datetime

# Dates are stored the way the venue team types them on the admin screen.
DATE_FORMAT = "%d/%m/%Y %H:%M"


def create_event(conn, title: str, starts_at: datetime, capacity: int, price_cents: int) -> int:
    cur = conn.execute(
        "INSERT INTO events (title, starts_at, capacity, booked, price_cents) VALUES (?, ?, ?, 0, ?)",
        (title, starts_at.strftime(DATE_FORMAT), capacity, price_cents),
    )
    conn.commit()
    return cur.lastrowid


def get_event(conn, event_id: int):
    row = conn.execute("SELECT * FROM events WHERE id = ?", (event_id,)).fetchone()
    return dict(row) if row else None


def seats_left(event: dict) -> int:
    return event["capacity"] - event["booked"]


def upcoming(conn, now: datetime, limit: int = 10):
    """Events that start after `now`, soonest first."""
    now_str = now.strftime(DATE_FORMAT)
    rows = conn.execute(
        "SELECT * FROM events WHERE starts_at > ? ORDER BY starts_at LIMIT ?", (now_str, limit)
    ).fetchall()
    return [dict(r) for r in rows]
