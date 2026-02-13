"""Database schema initialization."""

from __future__ import annotations

from database.connection import get_connection


def init_db() -> None:
    """Initialize the database schema (idempotent)."""

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                project TEXT NOT NULL,
                module TEXT NOT NULL,
                layer TEXT NOT NULL,
                title_raw TEXT NOT NULL,
                title_generated TEXT NOT NULL,
                type TEXT NOT NULL,
                priority TEXT NOT NULL,
                story_points INTEGER DEFAULT 1,
                epic TEXT,
                description TEXT,
                start_date TEXT,
                due_date TEXT,
                status TEXT DEFAULT 'todo',
                impact_score INTEGER DEFAULT 3,
                energy_required INTEGER DEFAULT 2,
                execution_score REAL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )

        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_status
            ON tasks(status)
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_tasks_due_date
            ON tasks(due_date)
            """
        )

        conn.commit()
