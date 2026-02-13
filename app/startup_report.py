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


def generate_startup_report() -> str:
    """Generate startup catch-up report message (without mention prefix)."""

    try:
        active = _fetch_active_tasks()
        done_yesterday = _fetch_done_yesterday()
    except Exception:
        msg = build_box("🚀  STARTUP CATCH-UP", "⚠️ Tidak bisa mengambil data task.")
        return truncate_discord(msg)

    lines: list[str] = []

    lines.append("🔥 ACTIVE TASKS")
    lines.append("──────────────────────")
    if not active:
        lines.append("Tidak ada task.")
    else:
        for idx, t in enumerate(active[:20]):
            tid = t.get("id")
            pr = str(t.get("priority") or "").title()
            proj = str(t.get("project") or "-")
            status = str(t.get("status") or "")
            title_raw = str(t.get("title_raw") or "").strip()

            lines.append(f"🆔 {tid} | 🔥 {pr} | 📦 {proj}")
            lines.append(f"{_status_icon(status)} {_status_label(status)}")
            lines.append(title_raw)

            if idx != min(len(active), 20) - 1:
                lines.append("")
                lines.append("──────────────────────")
                lines.append("")

    lines.append("")
    lines.append("✅ DONE YESTERDAY")
    lines.append("──────────────────────")
    if not done_yesterday:
        lines.append("Tidak ada task.")
    else:
        for idx, t in enumerate(done_yesterday[:20]):
            tid = t.get("id")
            proj = str(t.get("project") or "-")
            title_raw = str(t.get("title_raw") or "").strip()

            lines.append(f"🆔 {tid} | 📦 {proj}")
            lines.append("🔵 DONE")
            lines.append(title_raw)

            if idx != min(len(done_yesterday), 20) - 1:
                lines.append("")
                lines.append("──────────────────────")
                lines.append("")

    lines.append("━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Total Active : {len(active)}")
    lines.append(f"Done Yesterday : {len(done_yesterday)}")
    lines.append("━━━━━━━━━━━━━━━━━━━━━━")

    msg = build_box("🚀  STARTUP CATCH-UP", "\n".join(lines))
    return truncate_discord(msg)


def build_startup_report_message() -> str:
    """Build full Discord message including mention prefix."""

    user_id = os.environ.get("DISCORD_USER_ID")
    return truncate_discord(_mention_prefix(user_id) + generate_startup_report())
