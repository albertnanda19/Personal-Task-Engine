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


def list_tasks_paginated_for_bot(
    *,
    kind: str,
    page: int,
    page_size: int,
) -> tuple[list[dict], dict]:
    """List tasks for bot with pagination + totals.

    kind:
        - all
        - active (todo + in_progress)
        - done
        - today (created_at date = today)
        - todo
        - progress (in_progress)
    """

    kind = str(kind or "").lower().strip()
    page = int(page)
    page_size = int(page_size)
    if page <= 0:
        page = 1
    if page_size <= 0:
        page_size = 15

    offset = (page - 1) * page_size

    today_ymd = datetime.now().date().isoformat()

    where = ""
    params: list = []
    if kind == "all":
        where = ""
    elif kind == "active":
        where = "WHERE status IN ('todo','in_progress')"
    elif kind == "done":
        where = "WHERE status = 'done'"
    elif kind == "today":
        where = "WHERE substr(created_at, 1, 10) = ?"
        params.append(today_ymd)
    elif kind == "todo":
        where = "WHERE status = 'todo'"
    elif kind == "progress":
        where = "WHERE status = 'in_progress'"
    else:
        where = ""

    with get_connection() as conn:
        cur = conn.execute(
            f"SELECT * FROM tasks {where} ORDER BY created_at DESC LIMIT ? OFFSET ?",
            tuple(params + [page_size, offset]),
        )
        tasks = [dict(r) for r in cur.fetchall()]

        # Totals used for summary footer. Keep DB logic unchanged: only counting.
        cur_a = conn.execute(
            "SELECT COUNT(1) FROM tasks WHERE status IN ('todo','in_progress')"
        )
        total_active = int(cur_a.fetchone()[0])

        cur_d = conn.execute("SELECT COUNT(1) FROM tasks WHERE status = 'done'")
        total_completed = int(cur_d.fetchone()[0])

        cur_all = conn.execute("SELECT COUNT(1) FROM tasks")
        total_all = int(cur_all.fetchone()[0])

        cur_kind = conn.execute(
            f"SELECT COUNT(1) FROM tasks {where}",
            tuple(params),
        )
        total_kind = int(cur_kind.fetchone()[0])

    meta = {
        "page": page,
        "page_size": page_size,
        "total_kind": total_kind,
        "total_active": total_active,
        "total_completed": total_completed,
        "total_all": total_all,
    }
    return tasks, meta


def delete_task_for_bot(task_id: int) -> bool:
    """Hard delete a task by id.

    Returns True if a row was deleted, otherwise False.
    """

    task_id = int(task_id)
    with get_connection() as conn:
        conn.execute("BEGIN")
        cur = conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
        conn.commit()
        return int(cur.rowcount or 0) > 0


def search_tasks_for_bot(
    *,
    scope: str,
    keyword: str | None,
    limit: int = 20,
    offset: int = 0,
) -> tuple[list[dict], int]:
    """Search tasks by scope and optional keyword.

    - scope: all|active|todo|progress|done
    - keyword: single word, case-insensitive, searched via LIKE across key columns

    Returns: (rows, total_matches)
    """

    scope = str(scope or "").lower().strip()
    kw = str(keyword or "").strip().lower()
    if not kw:
        kw = ""

    conditions: list[str] = []
    params: list = []

    if scope == "active":
        conditions.append("status IN (?, ?)")
        params.extend(["todo", "in_progress"])
    elif scope == "todo":
        conditions.append("status = ?")
        params.append("todo")
    elif scope == "progress":
        conditions.append("status = ?")
        params.append("in_progress")
    elif scope == "done":
        conditions.append("status = ?")
        params.append("done")
    elif scope == "all":
        pass
    else:
        # Unknown scope treated as all; validation is done in command layer.
        pass

    if kw:
        like = f"%{kw}%"
        conditions.append(
            "("
            "LOWER(COALESCE(title_raw,'')) LIKE ? "
            "OR LOWER(COALESCE(project,'')) LIKE ? "
            "OR LOWER(COALESCE(description,'')) LIKE ? "
            "OR LOWER(COALESCE(type,'')) LIKE ? "
            "OR LOWER(COALESCE(priority,'')) LIKE ?"
            ")"
        )
        params.extend([like, like, like, like, like])

    where = ""
    if conditions:
        where = " WHERE " + " AND ".join(conditions)

    order_by = (
        " ORDER BY CASE status "
        "WHEN 'in_progress' THEN 1 "
        "WHEN 'todo' THEN 2 "
        "WHEN 'done' THEN 3 "
        "ELSE 99 END, created_at DESC"
    )

    limit = int(limit)
    offset = int(offset)
    if limit <= 0:
        limit = 20
    if offset < 0:
        offset = 0

    with get_connection() as conn:
        cur_c = conn.execute(f"SELECT COUNT(1) FROM tasks{where}", tuple(params))
        total = int(cur_c.fetchone()[0])

        cur = conn.execute(
            f"SELECT * FROM tasks{where}{order_by} LIMIT ? OFFSET ?",
            tuple(params + [limit, offset]),
        )
        rows = [dict(r) for r in cur.fetchall()]

    return rows, total
