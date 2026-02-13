"""Task data access layer.

All queries are parameterized and write operations commit.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from database.connection import get_connection


def create_task(data: dict[str, Any]) -> int:
    """Insert a new task row and return the inserted row id."""

    sql = """
        INSERT INTO tasks (
            project,
            module,
            layer,
            title_raw,
            title_generated,
            type,
            priority,
            story_points,
            epic,
            description,
            start_date,
            due_date,
            status,
            impact_score,
            energy_required,
            execution_score,
            created_at,
            updated_at
        ) VALUES (
            :project,
            :module,
            :layer,
            :title_raw,
            :title_generated,
            :type,
            :priority,
            :story_points,
            :epic,
            :description,
            :start_date,
            :due_date,
            :status,
            :impact_score,
            :energy_required,
            :execution_score,
            :created_at,
            :updated_at
        )
    """

    with get_connection() as conn:
        cur = conn.execute(sql, data)
        conn.commit()
        return int(cur.lastrowid)


def get_all_tasks() -> list[dict[str, Any]]:
    """Return all tasks as a list of dicts (ordered newest first)."""

    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM tasks ORDER BY created_at DESC")
        return [dict(row) for row in cur.fetchall()]


def get_tasks_by_status(status: str) -> list[dict[str, Any]]:
    """Return tasks filtered by status."""

    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC", (status,)
        )
        return [dict(row) for row in cur.fetchall()]


def get_task_by_id(task_id: int) -> dict[str, Any] | None:
    """Return a single task by id, or None if not found."""

    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,))
        row = cur.fetchone()
        return dict(row) if row else None


def get_overdue_tasks(today_iso: str | None = None) -> list[dict[str, Any]]:
    """Return overdue tasks.

    Overdue definition:
    - due_date exists
    - due_date < today
    - status != done
    """

    today = today_iso or date.today().isoformat()

    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM tasks
            WHERE due_date IS NOT NULL
              AND due_date != ''
              AND due_date < ?
              AND lower(status) != 'done'
            ORDER BY due_date ASC
            """,
            (today,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_oldest_todo() -> dict[str, Any] | None:
    """Return the oldest todo task by created_at, or None."""

    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM tasks
            WHERE lower(status) = 'todo'
            ORDER BY created_at ASC
            LIMIT 1
            """
        )
        row = cur.fetchone()
        return dict(row) if row else None


def get_done_tasks_last_7_days(start_date_iso: str | None = None) -> list[dict[str, Any]]:
    """Return done tasks whose updated_at is within the last 7 days.

    Notes:
    - updated_at and created_at are stored as ISO datetime strings.
    - We filter by updated_at >= start_date_iso (default: today - 7 days).
    """

    start = start_date_iso or (date.today() - timedelta(days=7)).isoformat()

    with get_connection() as conn:
        cur = conn.execute(
            """
            SELECT *
            FROM tasks
            WHERE lower(status) = 'done'
              AND updated_at >= ?
            ORDER BY updated_at DESC
            """,
            (start,),
        )
        return [dict(row) for row in cur.fetchall()]


def update_task_status(task_id: int, status: str, updated_at: str) -> int:
    """Update a task status; returns number of affected rows."""

    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, updated_at, task_id),
        )
        conn.commit()
        return int(cur.rowcount)


def update_execution_score(task_id: int, score: float) -> int:
    """Update a task execution_score; returns number of affected rows."""

    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE tasks SET execution_score = ? WHERE id = ?",
            (float(score), task_id),
        )
        conn.commit()
        return int(cur.rowcount)


def delete_task(task_id: int) -> int:
    """Delete a task; returns number of affected rows."""

    with get_connection() as conn:
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return int(cur.rowcount)
