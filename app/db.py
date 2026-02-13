"""Direct SQLite writes for Discord bot commands.

Phase 6: insert_task writes directly to the existing `tasks` table.

Note: The project schema has more required columns than the Discord command provides.
We fill required fields with deterministic defaults.
"""

from datetime import datetime, timezone

from database.connection import get_connection


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def insert_task(
    project: str,
    task_type: str,
    title: str,
    priority: str,
    story_points: int,
    description: str | None,
) -> int:
    """Insert a task and return its new id.

    Args:
        title: Raw title from Discord.
        priority: One of low/medium/high/urgent.
        story_points: Non-negative integer.
        description: Optional long description.

    Returns:
        New task id.
    """

    now = _utc_now_iso()

    payload = {
        "project": project,
        "module": "Inbox",
        "layer": "Bot",
        "title_raw": title,
        "title_generated": f"([{project}] [{task_type}] {title})",
        "type": task_type,
        "priority": str(priority).lower(),
        "story_points": int(story_points),
        "epic": None,
        "description": description,
        "start_date": None,
        "due_date": None,
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


def get_task_for_bot(task_id: int) -> dict | None:
    with get_connection() as conn:
        cur = conn.execute("SELECT * FROM tasks WHERE id = ?", (int(task_id),))
        row = cur.fetchone()
        return dict(row) if row else None


def update_task_status_for_bot(task_id: int, status: str) -> int:
    now = _utc_now_iso()
    with get_connection() as conn:
        cur = conn.execute(
            "UPDATE tasks SET status = ?, updated_at = ? WHERE id = ?",
            (status, now, int(task_id)),
        )
        conn.commit()
        return int(cur.rowcount)


def list_tasks_for_bot(status: str | None, limit: int = 20) -> list[dict]:
    limit = int(limit)
    if limit <= 0:
        limit = 20

    with get_connection() as conn:
        if status is None:
            cur = conn.execute(
                "SELECT * FROM tasks ORDER BY created_at DESC LIMIT ?",
                (limit,),
            )
        else:
            cur = conn.execute(
                "SELECT * FROM tasks WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit),
            )
        return [dict(r) for r in cur.fetchall()]
