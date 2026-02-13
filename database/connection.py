"""SQLite connection utilities."""

import sqlite3

from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection configured with Row row_factory."""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def test_connection() -> bool:
    """Test database connectivity.

    Returns True if a connection can be opened and a simple query succeeds.
    """

    try:
        with get_connection() as conn:
            conn.execute("SELECT 1;")
        return True
    except Exception as exc:
        print(f"Database connection test failed: {exc}")
        return False
