from bookings.errors import EmailTaken


def register(conn, email: str, name: str) -> int:
    """Create a user account. Each email address may only be registered once."""
    existing = conn.execute("SELECT id FROM users WHERE email = ?", (email,)).fetchone()
    if existing:
        raise EmailTaken(email)
    cur = conn.execute("INSERT INTO users (email, name) VALUES (?, ?)", (email, name))
    conn.commit()
    return cur.lastrowid


def find_by_email(conn, email: str):
    row = conn.execute("SELECT * FROM users WHERE email = ?", (email,)).fetchone()
    return dict(row) if row else None
