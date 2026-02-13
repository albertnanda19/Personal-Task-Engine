"""SQLite connection utilities."""

from __future__ import annotations

import sqlite3

from config import DB_PATH


def get_connection() -> sqlite3.Connection:
    """Return a SQLite connection configured with Row row_factory."""

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn
