import os
from datetime import datetime, timedelta

from database.connection import get_connection
from app.list_renderer import format_priority, format_status, pad_id, truncate
from app.ui import buildEmbed, build_box, truncate_discord


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


def _task_line_compact(task: dict) -> str:
    tid = pad_id(task.get("id"))
    pr_emoji, pr_label = format_priority(task.get("priority"))
    st_emoji, st_label = format_status(task.get("status"))
    proj = truncate(str(task.get("project") or "-"), 14)
    title = truncate(str(task.get("title_raw") or "-"), 40)
    st_label = st_label.replace("_", " ")
    return f"#{tid} • {pr_emoji} {pr_label} • {st_emoji} {st_label} • 📦 {proj}\n{title}"


def build_startup_report_payloads(user_id: str | None) -> list[dict]:
    """Embed-style startup report.

    Returns a list of Discord API payloads (each payload can contain 1+ embeds).
    """

    try:
        active = _fetch_active_tasks()
        done_yesterday = _fetch_done_yesterday()
    except Exception:
        embed = buildEmbed(
            title="🚀 Startup Catch-up",
            description="⚠️ Tidak bisa mengambil data task.",
            color=15158332,
            fields=[],
            footer=None,
            timestamp=None,
        )
        return [
            {
                "content": f"<@{user_id}>" if user_id else "",
                "embeds": [embed],
                "allowed_mentions": {"parse": [], "users": [str(user_id)]} if user_id else {"parse": []},
            }
        ]

    active_head = active[:5]
    active_remaining = max(len(active) - len(active_head), 0)
    done_head = done_yesterday[:5]
    done_remaining = max(len(done_yesterday) - len(done_head), 0)

    active_value = "\n\n".join([_task_line_compact(t) for t in active_head]) if active_head else "-"
    if active_remaining > 0:
        active_value += f"\n\n... and {active_remaining} more"

    done_value = "\n\n".join([_task_line_compact(t) for t in done_head]) if done_head else "-"
    if done_remaining > 0:
        done_value += f"\n\n... and {done_remaining} more"

    fields = [
        {"name": "Active Tasks", "value": active_value, "inline": False},
        {"name": "Done Yesterday", "value": done_value, "inline": False},
    ]

    embed1 = buildEmbed(
        title="🚀 Startup Catch-up",
        description=None,
        color=3447003,
        fields=fields,
        footer=f"Active: {len(active)} • Done Yesterday: {len(done_yesterday)}",
        timestamp=None,
    )

    embeds = [embed1]

    # Optional second embed if active is large
    if len(active) > 5:
        extra = active[5:15]
        extra_value = "\n\n".join([_task_line_compact(t) for t in extra]) if extra else "-"
        if len(active) > 15:
            extra_value += f"\n\n... and {len(active) - 15} more"

        embed2 = buildEmbed(
            title="🚀 Startup Catch-up (More Active)",
            description=None,
            color=3447003,
            fields=[{"name": "Active Tasks (cont.)", "value": extra_value, "inline": False}],
            footer=None,
            timestamp=None,
        )
        embeds.append(embed2)

    allowed_mentions = {"parse": []}
    content = ""
    if user_id:
        content = f"<@{user_id}>"
        allowed_mentions = {"parse": [], "users": [str(user_id)]}

    # One message containing up to 2 embeds.
    return [{"content": content, "embeds": embeds, "allowed_mentions": allowed_mentions}]
