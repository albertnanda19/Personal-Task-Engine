"""Execution scoring logic.

Phase 2: Dynamic execution score based on priority, due date, impact, story points,
and status.

Scoring formula:
    execution_score =
        priority_weight
        + due_weight
        + (impact_score * 2)
        + max(0, 5 - story_points)

Rules:
- If status == 'done': execution_score = 0
- If status == 'doing': execution_score += 2

Dates are compared using current local date and ISO YYYY-MM-DD strings.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from models.task_model import get_all_tasks, update_execution_score


_PRIORITY_WEIGHTS: dict[str, int] = {
    "low": 1,
    "medium": 3,
    "high": 5,
    "urgent": 8,
}


def _parse_iso_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError:
        return None


def _to_int(value: Any, default: int) -> int:
    try:
        if value is None:
            return default
        return int(value)
    except (TypeError, ValueError):
        return default


def calculate_execution_score(task: Mapping[str, Any]) -> float:
    """Calculate execution score for a single task."""

    status = str(task.get("status") or "todo").strip().lower()
    if status == "done":
        return 0.0

    priority = str(task.get("priority") or "medium").strip().lower()
    priority_weight = _PRIORITY_WEIGHTS.get(priority, 3)

    story_points = _to_int(task.get("story_points"), default=1)
    impact_score = _to_int(task.get("impact_score"), default=3)

    due = _parse_iso_date(task.get("due_date"))
    today = date.today()

    due_weight = 0
    if due is not None:
        if due < today:
            due_weight = 10
        elif due == today:
            due_weight = 7
        elif (due - today).days <= 3:
            due_weight = 4

    score = (
        priority_weight
        + due_weight
        + (impact_score * 2)
        + max(0, 5 - story_points)
    )

    if status == "doing":
        score += 2

    return float(score)


def recalculate_all_scores() -> int:
    """Recalculate execution_score for all tasks.

    Returns number of tasks updated.
    """

    tasks = get_all_tasks()
    updated_count = 0

    for task in tasks:
        task_id = task.get("id")
        if task_id is None:
            continue

        score = calculate_execution_score(task)
        update_execution_score(int(task_id), score)
        updated_count += 1

    return updated_count
