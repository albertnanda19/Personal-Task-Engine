"""Task business layer.

Phase 1: formatting + defaults only.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from models.task_model import (
    create_task,
    delete_task,
    get_all_tasks,
    get_task_by_id,
    get_tasks_by_status,
    update_execution_score,
    update_task_status,
)

from services.scoring_service import calculate_execution_score


def generate_formatted_title(project: str, module: str, layer: str, title_raw: str) -> str:
    """Generate the formatted task title.

    Format: ([Project] [Module] [Layer] Title)
    """

    return f"([{project}] [{module}] [{layer}] {title_raw})"


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def create_task_with_formatting(data: dict[str, Any]) -> int:
    """Create a task with generated title and timestamps."""

    now = _utc_now_iso()

    payload: dict[str, Any] = {
        **data,
        "title_raw": data["title_raw"],
        "title_generated": generate_formatted_title(
            data["project"], data["module"], data["layer"], data["title_raw"]
        ),
        "created_at": now,
        "updated_at": now,
        "status": data.get("status") or "todo",
        "story_points": data.get("story_points") if data.get("story_points") is not None else 1,
        "impact_score": data.get("impact_score") if data.get("impact_score") is not None else 3,
        "energy_required": data.get("energy_required")
        if data.get("energy_required") is not None
        else 2,
        "execution_score": data.get("execution_score")
        if data.get("execution_score") is not None
        else 0,
        "epic": data.get("epic"),
        "description": data.get("description"),
        "start_date": data.get("start_date"),
        "due_date": data.get("due_date"),
    }

    required_keys = [
        "project",
        "module",
        "layer",
        "title_raw",
        "title_generated",
        "type",
        "priority",
        "created_at",
        "updated_at",
        "status",
    ]
    for key in required_keys:
        if payload.get(key) in (None, ""):
            raise ValueError(f"Missing required field: {key}")

    payload["execution_score"] = calculate_execution_score(payload)

    return create_task(payload)


def list_tasks(status: str | None = None) -> list[dict[str, Any]]:
    """List tasks, optionally filtered by status."""

    if status:
        return get_tasks_by_status(status)
    return get_all_tasks()


def set_task_status(task_id: int, status: str) -> int:
    """Update task status and updated_at."""

    updated = update_task_status(task_id=task_id, status=status, updated_at=_utc_now_iso())
    if updated == 0:
        return 0

    task = get_task_by_id(task_id)
    if task is None:
        return updated

    score = calculate_execution_score(task)
    update_execution_score(task_id, score)

    return updated


def remove_task(task_id: int) -> int:
    """Delete a task by id."""

    return delete_task(task_id)
