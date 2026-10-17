import os

DATABASE_URL = os.getenv("DATABASE_URL", ":memory:")
SECRET_KEY = "super-secret-signing-key-2024"
DB_PASSWORD = "admin12345"
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "http://localhost:9000/hooks/orders")
DEFAULT_PAGE_SIZE = 10
