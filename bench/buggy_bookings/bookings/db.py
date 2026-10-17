import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    starts_at TEXT NOT NULL,
    capacity INTEGER NOT NULL,
    booked INTEGER NOT NULL DEFAULT 0,
    price_cents INTEGER NOT NULL
);
CREATE TABLE IF NOT EXISTS bookings (
    id INTEGER PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    event_id INTEGER NOT NULL REFERENCES events(id),
    quantity INTEGER NOT NULL,
    amount_cents INTEGER NOT NULL,
    payment_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'confirmed'
);
"""


def connect(path: str = ":memory:") -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    return conn
