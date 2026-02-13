import os
from datetime import datetime, timedelta

from database.connection import get_connection
from app.ui import build_box, truncate_discord


def _mention_prefix(user_id: str | int | None) -> str:
    if user_id is None:
        return ""
    return f"<@{user_id}>\n\n"


def _status_icon(status: str) -> str:
    s = str(status or "").lower()
    if s == "todo":
        return "🟢"
    if s == "in_progress":
        return "🟡"
    if s == "done":
        return "🔵"
    return "⚠️"


def _status_label(status: str) -> str:
    s = str(status or "").lower()
    if s == "todo":
        return "TODO"
    if s == "in_progress":
        return "IN PROGRESS"
    if s == "done":
        return "DONE"
    return s.upper() or "-"


def _status_short(status: str) -> str:
    s = str(status or "").lower()
    if s == "todo":
        return "🟢 TD"
    if s == "in_progress":
        return "🟡 IP"
    if s == "done":
        return "🔵 DN"
    return "⚠️ -"


def _priority_rank(priority: str) -> int:
    p = str(priority or "").lower()
    if p == "urgent":
        return 1
    if p == "high":
        return 2
    if p == "medium":
        return 3
    if p == "low":
        return 4
    return 99


def _priority_short(priority: str) -> str:
    p = str(priority or "").lower()
    if p == "urgent":
        return "U"
    if p == "high":
        return "H"
    if p == "medium":
        return "M"
    if p == "low":
        return "L"
    return "-"


def _truncate_title(title: str, limit: int = 30) -> str:
    title = str(title or "").strip()
    limit = int(limit)
    if limit <= 3:
        return title[:limit]
    if len(title) <= limit:
        return title
    return title[: limit - 3] + "..."


def _fetch_active_tasks() -> list[dict]:
    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM tasks WHERE status IN ('todo','in_progress') ORDER BY created_at DESC"
        )
        rows = [dict(r) for r in cur.fetchall()]

    # Match required ordering:
    # - priority rank (Urgent/High/Medium/Low)
    # - created_at DESC
    # We do this via two stable sorts.
    rows.sort(key=lambda r: str(r.get("created_at") or ""), reverse=True)
    rows.sort(key=lambda r: _priority_rank(r.get("priority")), reverse=False)
    return rows


def _fetch_done_yesterday() -> list[dict]:
    today = datetime.now().date()
    yesterday = today - timedelta(days=1)
    ymd = yesterday.isoformat()

    with get_connection() as conn:
        cur = conn.execute(
            "SELECT * FROM tasks WHERE status = 'done' AND substr(updated_at, 1, 10) = ? ORDER BY updated_at DESC",
            (ymd,),
        )
        return [dict(r) for r in cur.fetchall()]


def _count_status(rows: list[dict], status: str) -> int:
    status = str(status or "").lower()
    c = 0
    for r in rows:
        if str(r.get("status") or "").lower() == status:
            c += 1
    return c


def _sep() -> str:
    return "━━━━━━━━━━━━━━━━━━━━━━━━━━"


def _build_active_table(active: list[dict], limit: int) -> tuple[str, int]:
    limit = int(limit)
    shown = active[: max(limit, 0)]
    remaining = max(len(active) - len(shown), 0)

    if not shown:
        return "None.", remaining

    lines: list[str] = []
    lines.append("ID  | P  | Project  | Type   | Status | Title")
    lines.append("----+----+----------+--------+--------+-------------------------")
    for t in shown:
        tid = str(t.get("id") or "")
        p = _priority_short(t.get("priority"))
        proj = str(t.get("project") or "-")
        typ = str(t.get("type") or "-")
        st = _status_short(t.get("status"))
        title = _truncate_title(t.get("title_raw") or "", 30)

        lines.append(
            f"{tid:<4} | {p:<2} | {proj[:10]:<8} | {typ[:6]:<6} | {st:<6} | {title}"
        )

    if remaining > 0:
        lines.append("")
        lines.append(f"... and {remaining} more")

    return "\n".join(lines), remaining


def _build_done_table(done: list[dict], limit: int) -> tuple[str, int]:
    limit = int(limit)
    shown = done[: max(limit, 0)]
    remaining = max(len(done) - len(shown), 0)

    if not shown:
        return "None.", remaining

    lines: list[str] = []
    lines.append("ID  | Project  | Title")
    lines.append("----+----------+-----------------------------")
    for t in shown:
        tid = str(t.get("id") or "")
        proj = str(t.get("project") or "-")
        title = _truncate_title(t.get("title_raw") or "", 30)
        lines.append(f"{tid:<4} | {proj[:10]:<8} | {title}")

    if remaining > 0:
        lines.append("")
        lines.append(f"... and {remaining} more")

    return "\n".join(lines), remaining


def _build_report(active: list[dict], done_yesterday: list[dict], active_limit: int, done_limit: int) -> str:
    todo_count = _count_status(active, "todo")
    ip_count = _count_status(active, "in_progress")

    overview = "\n".join(
        [
            "📊 OVERVIEW",
            f"Active      : {len(active)}",
            f"In Progress : {ip_count}",
            f"Todo        : {todo_count}",
            f"Done Yesterday : {len(done_yesterday)}",
        ]
    )

    active_table, _active_rem = _build_active_table(active, active_limit)
    done_table, _done_rem = _build_done_table(done_yesterday, done_limit)

    body = "\n".join(
        [
            overview,
            "",
            _sep(),
            "🔥 ACTIVE TASKS",
            _sep(),
            "",
            active_table,
            "",
            _sep(),
            "✅ DONE YESTERDAY",
            _sep(),
            "",
            done_table,
            "",
            _sep(),
            "Legend:",
            "P  = Priority (U/H/M/L)",
            "TD = TODO",
            "IP = IN PROGRESS",
            "DN = DONE",
            _sep(),
        ]
    )

    return build_box("🚀 STARTUP SUMMARY", body)


def generate_startup_report() -> str:
    """Generate startup catch-up report message (without mention prefix)."""

    try:
        active = _fetch_active_tasks()
        done_yesterday = _fetch_done_yesterday()
    except Exception:
        msg = build_box("🚀 STARTUP SUMMARY", "⚠️ Tidak bisa mengambil data task.")
        return truncate_discord(msg)

    # Default limits per spec
    candidates = [
        (15, 10, False),
        (10, 10, True),
        (5, 10, True),
        (0, 10, True),
        (0, 5, True),
        (0, 0, True),
    ]

    limit_soft = 1900
    last = ""
    for a_limit, d_limit, add_note in candidates:
        msg = _build_report(active, done_yesterday, a_limit, d_limit)
        if add_note:
            msg = msg + "\n... (truncated due to length)"
        last = msg
        if len(msg) <= limit_soft:
            return truncate_discord(msg)

    return truncate_discord(last)


def build_startup_report_message() -> str:
    """Build full Discord message including mention prefix."""

    user_id = os.environ.get("DISCORD_USER_ID")
    return truncate_discord(_mention_prefix(user_id) + generate_startup_report())
