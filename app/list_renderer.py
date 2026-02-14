from app.ui import build_box


SEP = "━━━━━━━━━━━━━━━━━━━━━━━━━━"
ITEM_SEP = "────────────────────────────"


STATUS_EMOJI = {
    "todo": "🟢",
    "in_progress": "🟡",
    "done": "🔵",
}

PRIORITY_EMOJI = {
    "low": "🟢",
    "medium": "🟡",
    "high": "🔥",
    "urgent": "🚨",
}


def truncate(text: str, max_length: int = 60) -> str:
    text = str(text or "").strip()
    max_length = int(max_length)
    if max_length <= 3:
        return text[:max_length]
    if len(text) <= max_length:
        return text
    return text[: max_length - 3] + "..."


def pad_id(value) -> str:
    try:
        n = int(value)
    except Exception:
        return "???"
    if n < 0:
        return "???"
    return f"{n:03d}"


def format_priority(priority: str) -> tuple[str, str]:
    p = str(priority or "").lower().strip()
    emoji = PRIORITY_EMOJI.get(p, "⚠️")
    label = p.upper() if p else "-"
    return emoji, label


def format_status(status: str) -> tuple[str, str]:
    s = str(status or "").lower().strip()
    emoji = STATUS_EMOJI.get(s, "⚠️")
    label = "IN_PROGRESS" if s == "in_progress" else s.upper() if s else "-"
    return emoji, label


def _task_card(task: dict) -> str:
    tid = pad_id(task.get("id"))
    pr_emoji, pr_label = format_priority(task.get("priority"))
    st_emoji, st_label = format_status(task.get("status"))

    project = truncate(task.get("project") or "-", 20)
    task_type = truncate(task.get("type") or "-", 12)
    title = truncate(task.get("title_raw") or "", 60)
    desc_raw = (task.get("description") or "").strip()
    desc = truncate(desc_raw, 80) if desc_raw else ""

    line1 = f"🆔 {tid} | {pr_emoji} {pr_label} | 📦 {project} | 🏷️ {task_type}"
    line2 = f"{st_emoji} {st_label:<11} {title}"
    if desc:
        line3 = f"📝 {desc}"
        return "\n".join([line1, line2, line3])
    return "\n".join([line1, line2])


def render_task_card(task: dict) -> str:
    return _task_card(task)


def render_task_list(
    *,
    tasks: list[dict],
    title: str,
    group_by_status: bool = False,
    page: int = 1,
    page_size: int = 15,
    total_active: int | None = None,
    total_completed: int | None = None,
    total_all: int | None = None,
    total_label: str | None = None,
    total_value: int | None = None,
    kind_for_hint: str | None = None,
) -> str:
    header_title = f"📋  TASK LIST ({title})" if title else "📋  TASK LIST"

    if not tasks:
        body = "\n".join(["📭 Tidak ada task ditemukan."])
        return build_box(header_title, body)

    lines: list[str] = []

    if group_by_status:
        active = [t for t in tasks if str(t.get("status") or "").lower() != "done"]
        done = [t for t in tasks if str(t.get("status") or "").lower() == "done"]

        if active:
            lines.append("🟢 ACTIVE")
            lines.append(ITEM_SEP)
            for t in active:
                lines.append(_task_card(t))
                lines.append(ITEM_SEP)
            lines.append("")

        if done:
            lines.append("🔵 COMPLETED")
            lines.append(ITEM_SEP)
            for t in done:
                lines.append(_task_card(t))
                lines.append(ITEM_SEP)
    else:
        for t in tasks:
            lines.append(_task_card(t))
            lines.append(ITEM_SEP)

    # Summary footer
    footer_lines: list[str] = []
    if total_active is not None and total_completed is not None and total_all is not None:
        footer_lines.extend(
            [
                SEP,
                f"Total Active     : {total_active}",
                f"Total Completed  : {total_completed}",
                f"Total All        : {total_all}",
                SEP,
            ]
        )
    elif total_active is not None and title == "ACTIVE":
        footer_lines.extend(
            [
                SEP,
                f"Total Active : {total_active}",
                SEP,
            ]
        )
    elif total_completed is not None and title == "DONE":
        footer_lines.extend(
            [
                SEP,
                f"Total Completed : {total_completed}",
                SEP,
            ]
        )
    elif total_label is not None and total_value is not None:
        footer_lines.extend(
            [
                SEP,
                f"{total_label} : {total_value}",
                SEP,
            ]
        )

    # Pagination footer
    if total_value is not None and page_size > 0:
        total_pages = (int(total_value) + int(page_size) - 1) // int(page_size)
        if total_pages > 1:
            hint_kind = str(kind_for_hint or title).lower()
            footer_lines.extend(
                [
                    f"Page {page} of {total_pages}",
                    f"Gunakan !list {hint_kind} {page + 1} untuk halaman berikutnya",
                ]
            )

    body = "\n".join(lines + ([""] + footer_lines if footer_lines else []))
    return build_box(header_title, body)
