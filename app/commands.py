"""Discord command parsing.

Phase 6: Parse !add command.
"""

from __future__ import annotations

from datetime import datetime


_ALLOWED_PRIORITIES = {"low", "medium", "high", "urgent"}


def _is_valid_date(value: str) -> bool:
    try:
        datetime.strptime(value, "%Y-%m-%d")
        return True
    except ValueError:
        return False


def parse_add_command(message: str) -> dict | None:
    """Parse a Discord add-task command.

    Expected format:
        !add | Priority | Title | DueDate | StoryPoint

    Rules:
    - Must start with !add
    - Split by '|'
    - Priority and Title required
    - DueDate optional (YYYY-MM-DD)
    - StoryPoint optional (int, default 0)

    Returns a dict on success, None on invalid input.
    """

    if not message:
        return None

    raw = message.strip()
    if not raw.lower().startswith("!add"):
        return None

    parts = [p.strip() for p in raw.split("|")]
    if not parts:
        return None

    if parts[0].strip().lower() != "!add":
        return None

    if len(parts) < 3:
        return None

    priority = parts[1].strip()
    title = parts[2].strip()

    if not priority or not title:
        return None

    priority_norm = priority.lower()
    if priority_norm not in _ALLOWED_PRIORITIES:
        return None

    due_date: str | None = None
    story_points = 0

    if len(parts) >= 4 and parts[3].strip():
        candidate = parts[3].strip()
        if not _is_valid_date(candidate):
            return None
        due_date = candidate

    if len(parts) >= 5 and parts[4].strip():
        try:
            story_points = int(parts[4].strip())
        except ValueError:
            return None
        if story_points < 0:
            return None

    return {
        "title": title,
        "priority": priority_norm,
        "story_points": story_points,
        "due_date": due_date,
    }
