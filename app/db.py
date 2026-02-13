"""Direct SQLite writes for Discord bot commands.

Phase 6: insert_task writes directly to the existing `tasks` table.

Note: The project schema has more required columns than the Discord command provides.
We fill required fields with deterministic defaults.
"""

from __future__ import annotations

from datetime import datetime, timezone

from database.connection import get_connection


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def insert_task(title: str, priority: str, story_points: int, due_date: str | None) -> int:
    """Insert a task and return its new id.

    Args:
        title: Raw title from Discord.
        priority: One of low/medium/high/urgent.
        story_points: Non-negative integer.
        due_date: Optional YYYY-MM-DD.

    Returns:
        New task id.
    """

    now = _utc_now_iso()

    payload = {
        "project": "Discord",
        "module": "Inbox",
        "layer": "Bot",
        "title_raw": title,
        "title_generated": f"([Discord] [Inbox] [Bot] {title})",
        "type": "task",
        "priority": priority,
        "story_points": int(story_points),
        "epic": None,
        "description": None,
        "start_date": None,
        "due_date": due_date,
        "status": "todo",
        "impact_score": 3,
        "energy_required": 2,
        "execution_score": 0,
        "created_at": now,
        "updated_at": now,
    }

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
        cur = conn.execute(sql, payload)
        conn.commit()
        return int(cur.lastrowid)
