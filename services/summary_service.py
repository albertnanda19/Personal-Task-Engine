"""Summary and analytics services.

Phase 3: Provide productivity dashboard and weekly report.
"""

from __future__ import annotations

from collections import Counter
from datetime import date, datetime, timedelta
from typing import Any

from models.task_model import (
    get_all_tasks,
    get_done_tasks_last_7_days,
    get_oldest_todo,
    get_overdue_tasks,
)


def _safe_fromisoformat(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def get_dashboard_summary() -> dict[str, Any]:
    """Return a structured dashboard summary."""

    tasks = get_all_tasks()
    total = len(tasks)

    status_counts = Counter(str(t.get("status") or "").lower() for t in tasks)

    overdue = get_overdue_tasks()

    active_scores = [
        float(t.get("execution_score") or 0)
        for t in tasks
        if str(t.get("status") or "").lower() != "done"
    ]
    avg_execution_score = (
        sum(active_scores) / len(active_scores) if active_scores else 0.0
    )

    top_3 = [
        t
        for t in tasks
        if str(t.get("status") or "").lower() != "done"
    ]
    top_3.sort(key=lambda t: float(t.get("execution_score") or 0), reverse=True)
    top_3 = top_3[:3]

    oldest_todo = get_oldest_todo()

    return {
        "total_tasks": total,
        "total_todo": int(status_counts.get("todo", 0)),
        "total_doing": int(status_counts.get("doing", 0)),
        "total_done": int(status_counts.get("done", 0)),
        "total_overdue": len(overdue),
        "average_execution_score": float(avg_execution_score),
        "top_3": top_3,
        "oldest_todo": oldest_todo,
    }


def get_weekly_report() -> dict[str, Any]:
    """Return a structured weekly performance report (last 7 days)."""

    done_tasks = get_done_tasks_last_7_days()

    tasks_completed = len(done_tasks)
    story_points_completed = sum(int(t.get("story_points") or 0) for t in done_tasks)

    completion_durations_days: list[float] = []
    for t in done_tasks:
        created_at = _safe_fromisoformat(t.get("created_at"))
        updated_at = _safe_fromisoformat(t.get("updated_at"))
        if created_at is None or updated_at is None:
            continue
        delta = updated_at - created_at
        completion_durations_days.append(delta.total_seconds() / 86400)

    avg_completion_time_days = (
        sum(completion_durations_days) / len(completion_durations_days)
        if completion_durations_days
        else 0.0
    )

    priority_counter = Counter(str(t.get("priority") or "").lower() for t in done_tasks)
    type_counter = Counter(str(t.get("type") or "").lower() for t in done_tasks)

    most_common_priority = priority_counter.most_common(1)[0][0] if priority_counter else None
    most_common_type = type_counter.most_common(1)[0][0] if type_counter else None

    return {
        "tasks_completed_7d": tasks_completed,
        "story_points_completed_7d": story_points_completed,
        "average_completion_time_days": float(avg_completion_time_days),
        "most_common_priority": most_common_priority,
        "most_common_type": most_common_type,
    }
