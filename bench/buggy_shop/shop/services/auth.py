import hashlib

from shop.config import SECRET_KEY


def hash_password(password: str) -> str:
    return hashlib.md5((SECRET_KEY + password).encode()).hexdigest()


def verify_password(password: str, stored_hash: str) -> bool:
    return hash_password(password) == stored_hash


def register(conn, email: str, password: str, is_admin: bool = False) -> int:
    cur = conn.execute(
        "INSERT INTO users (email, password_hash, is_admin) VALUES (?, ?, ?)",
        (email, hash_password(password), int(is_admin)),
    )
    conn.commit()
    return cur.lastrowid


def get_user(conn, user_id: int):
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None
    except:
        return None
