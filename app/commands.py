"""Discord command parsing.

Phase 6: Parse !add command.
"""

_ALLOWED_PRIORITIES = {"low", "medium", "high", "urgent"}


def parse_add_command(message: str) -> dict | None:
    """Parse Phase 7 Discord add-task command.

    Format:
        !add
        project=Edlink
        type=Bug
        priority=High
        title=Fix login bug
        sp=3
        desc=Optional description

    Rules:
    - Multiline key=value pairs after !add
    - Ignore whitespace around key/value
    - Required: project, type, priority, title
    - Optional: sp (default 0), desc
    - priority: Low/Medium/High/Urgent (case-insensitive)
    """

    if not message:
        return None

    lines = [ln.strip() for ln in str(message).splitlines()]
    lines = [ln for ln in lines if ln]
    if not lines:
        return None

    if lines[0].lower() != "!add":
        return None

    fields: dict[str, str] = {}
    for ln in lines[1:]:
        if "=" not in ln:
            continue
        k, v = ln.split("=", 1)
        key = k.strip().lower()
        val = v.strip()
        if not key:
            continue
        if val == "":
            continue
        fields[key] = val

    project = (fields.get("project") or "").strip()
    task_type = (fields.get("type") or "").strip()
    priority_raw = (fields.get("priority") or "").strip()
    title = (fields.get("title") or "").strip()

    if not project or not task_type or not priority_raw or not title:
        return None

    priority_norm = priority_raw.lower()
    if priority_norm not in _ALLOWED_PRIORITIES:
        return None

    sp_raw = (fields.get("sp") or "").strip()
    story_points = 0
    if sp_raw:
        try:
            story_points = int(sp_raw)
        except Exception:
            return None
        if story_points < 0:
            return None

    desc = (fields.get("desc") or "").strip() or None

    return {
        "project": project,
        "type": task_type,
        "priority": priority_norm,
        "title": title,
        "story_points": story_points,
        "description": desc,
    }
