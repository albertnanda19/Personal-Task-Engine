"""Discord bot listener (polling).

Phase 6:
- Poll last 20 messages from a channel
- Parse !add commands
- Insert task into SQLite
- Reply with confirmation/error
- Persist last processed message id to avoid duplicates

Constraints:
- Standard library only
- Synchronous
"""

import json
import logging
import os
from datetime import datetime, timezone
import urllib.request


from app.commands import parse_add_command
from app.db import (
    delete_task_for_bot,
    get_task_for_bot,
    insert_task,
    list_tasks_for_bot,
    search_tasks_for_bot,
    update_task_status_for_bot,
)
from app.list_renderer import (
    format_priority,
    format_status,
    pad_id,
    render_task_card,
    render_task_list,
    truncate,
)
from app.startup_report import build_startup_report_payloads
from app.ui import buildEmbed, build_box, truncate_discord
from bot.discord_client import load_env


pending_delete: dict[int, str] = {}


PRIORITY_COLOR = {
    "low": 3066993,
    "medium": 15844367,
    "high": 15105570,
    "urgent": 15158332,
}

NEUTRAL_LIST_COLOR = 3447003


def _format_dt(value: str) -> str:
    s = str(value or "").strip()
    if not s or s == "-":
        return "-"
    if "T" in s:
        s = s.replace("T", " ")
    if "+" in s:
        s = s.split("+", 1)[0]
    if "Z" in s:
        s = s.replace("Z", "")
    # keep YYYY-MM-DD HH:MM
    if len(s) >= 16:
        return s[:16]
    return s


def _priority_color(priority: str) -> int:
    return int(PRIORITY_COLOR.get(str(priority or "").lower().strip(), NEUTRAL_LIST_COLOR))


def _setup_logger() -> logging.Logger:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    logs_dir = os.path.join(base, "logs")
    os.makedirs(logs_dir, exist_ok=True)

    logger = logging.getLogger("bot_listener")
    logger.setLevel(logging.INFO)

    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        fh = logging.FileHandler(os.path.join(logs_dir, "bot.log"))
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def _get_credentials() -> tuple[str | None, str | None, str | None]:
    load_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    user_id = os.environ.get("DISCORD_USER_ID")
    return token, channel_id, user_id


def _data_dir() -> str:
    base = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    d = os.path.join(base, "data")
    os.makedirs(d, exist_ok=True)
    return d


def _last_id_path() -> str:
    return os.path.join(_data_dir(), "last_message_id.txt")


def _read_last_message_id() -> int:
    path = _last_id_path()
    if not os.path.exists(path):
        return 0
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = f.read().strip()
        return int(raw) if raw else 0
    except Exception:
        return 0


def _write_last_message_id(message_id: int) -> None:
    path = _last_id_path()
    with open(path, "w", encoding="utf-8") as f:
        f.write(str(int(message_id)))


def _http_get_json(url: str, token: str, logger: logging.Logger):
    req = urllib.request.Request(
        url,
        method="GET",
        headers={
            "Authorization": f"Bot {token}",
            "Accept": "application/json",
            "User-Agent": "personal_task_engine/1.0 (+https://github.com/)",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return json.loads(body) if body else None
    except Exception as e:
        logger.exception("HTTP GET error: %s", e)
        return None


def _http_post_json(url: str, token: str, payload: dict, logger: logging.Logger) -> bool:
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={
            "Authorization": f"Bot {token}",
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": "personal_task_engine/1.0 (+https://github.com/)",
        },
    )

    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            status = int(getattr(resp, "status", 200))
            return 200 <= status < 300
    except Exception as e:
        logger.exception("HTTP POST error: %s", e)
        return False


def _build_allowed_mentions(user_id: str | None) -> dict:
    # Keep bot safe from unwanted mass mentions.
    # Allow mentioning only the intended user when provided.
    if not user_id:
        return {"parse": []}
    return {"parse": [], "users": [str(user_id)]}


def _build_message_payload(*, user_id: str | None, content: str | None, embeds: list[dict] | None) -> dict:
    payload: dict = {"allowed_mentions": _build_allowed_mentions(user_id)}
    if content is not None:
        payload["content"] = truncate_discord(str(content), 2000)
    if embeds:
        payload["embeds"] = embeds[:10]
    return payload


def _reply_payload(channel_id: str, token: str, payload: dict, logger: logging.Logger) -> None:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    _http_post_json(url, token, payload, logger)


def _reply(channel_id: str, token: str, content_or_payload, logger: logging.Logger) -> None:
    # Backward compatible: accept plain content string or full payload dict.
    if isinstance(content_or_payload, dict):
        _reply_payload(channel_id, token, content_or_payload, logger)
        return

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    _http_post_json(url, token, {"content": str(content_or_payload or "")}, logger)


def _reply_many(channel_id: str, token: str, payloads: list[dict], logger: logging.Logger) -> None:
    for p in payloads:
        _reply_payload(channel_id, token, p, logger)


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sleep_seconds(seconds: int) -> None:
    """Sleep without importing time (busy-wait)."""

    seconds = int(seconds)
    if seconds <= 0:
        return
    end = _utc_now().timestamp() + float(seconds)
    while _utc_now().timestamp() < end:
        pass


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


def _format_help(user_id: str | int | None) -> str:
    body = "\n".join(
        [
            "Quick Commands (copy-ready):",
            "",
            "➕ Create:",
            "```txt",
            "!add",
            "```",
            "",
            "📋 List:",
            "```txt",
            "!list all [keyword]",
            "```",
            "```txt",
            "!list active [keyword]",
            "```",
            "```txt",
            "!list todo [keyword]",
            "```",
            "```txt",
            "!list progress [keyword]",
            "```",
            "```txt",
            "!list done [keyword]",
            "```",
            "",
            "� Detail:",
            "```txt",
            "!detail <id>",
            "```",
            "",
            "�🔄 Update:",
            "```txt",
            "!progress <id>",
            "```",
            "```txt",
            "!done <id>",
            "```",
            "```txt",
            "!todo <id>",
            "```",
            "",
            "🗑️ Delete (safe):",
            "```txt",
            "!delete <id>",
            "```",
            "```txt",
            "!confirm <id>",
            "```",
            "```txt",
            "!cancel <id>",
            "```",
            "",
            "📄 Templates:",
            "```txt",
            "!template add",
            "```",
            "```txt",
            "!template update",
            "```",
            "",
            "Status Meaning:",
            "🟢 TODO",
            "🟡 IN PROGRESS",
            "🔵 DONE",
        ]
    )
    msg = build_box("📘  TASK BOT DOCUMENTATION", body)
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_error(user_id: str | int | None) -> str:
    body = "\n".join(
        [
            "Gunakan:",
            "!add",
            "project=...",
            "type=...",
            "priority=...",
            "title=...",
            "",
            "Ketik !help untuk dokumentasi.",
        ]
    )
    msg = build_box("❌  FORMAT ERROR", body)
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_delete_failed(user_id: str | int | None, reason: str) -> str:
    msg = build_box("⚠️  DELETE FAILED", reason)
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_delete_confirmation(user_id: str | int | None, task: dict) -> str:
    body = "\n".join(
        [
            "Anda yakin ingin menghapus task berikut?",
            "",
            render_task_card(task),
            "",
            "Ketik:",
            f"!confirm {int(task.get('id') or 0)}  → untuk menghapus",
            f"!cancel {int(task.get('id') or 0)}   → untuk membatalkan",
        ]
    )
    msg = build_box("⚠️  DELETE CONFIRMATION", body)
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_delete_success(user_id: str | int | None, task: dict) -> str:
    body = "\n".join(
        [
            "Task berikut berhasil dihapus:",
            "",
            render_task_card(task),
        ]
    )
    msg = build_box("🗑️  TASK DELETED", body)
    return truncate_discord(_mention_prefix(user_id) + msg)


def _parse_task_id_arg(parts: list[str]) -> tuple[int | None, str | None]:
    if len(parts) < 2:
        return None, "Gunakan: !delete <task_id>"

    raw_id = str(parts[1] or "").strip()
    try:
        task_id = int(raw_id)
    except Exception:
        return None, "Task ID harus angka. Contoh: !delete 3"

    if task_id <= 0:
        return None, "Task ID harus angka > 0."

    return task_id, None


def deleteCommandHandler(requester_user_id: str, raw_line: str) -> str:
    parts = str(raw_line or "").strip().split()
    task_id, err = _parse_task_id_arg(parts)
    if err:
        return _format_delete_failed(requester_user_id, err)

    existing = get_task_for_bot(task_id)
    if existing is None:
        return _format_delete_failed(requester_user_id, f"Task dengan ID {task_id} tidak ditemukan.")

    pending_delete[int(task_id)] = str(requester_user_id)
    return _format_delete_confirmation(requester_user_id, existing)


def confirmDeleteHandler(requester_user_id: str, raw_line: str) -> str:
    parts = str(raw_line or "").strip().split()
    task_id, err = _parse_task_id_arg(parts)
    if err:
        return _format_delete_failed(requester_user_id, "Gunakan: !confirm <task_id>")

    owner = pending_delete.get(int(task_id))
    if owner is None:
        return _format_delete_failed(requester_user_id, "Tidak ada request delete pending untuk ID tersebut.")

    if str(owner) != str(requester_user_id):
        return _format_delete_failed(requester_user_id, "Anda tidak berhak mengkonfirmasi delete ini.")

    existing = get_task_for_bot(task_id)
    if existing is None:
        pending_delete.pop(int(task_id), None)
        return _format_delete_failed(requester_user_id, f"Task dengan ID {task_id} tidak ditemukan.")

    try:
        ok = delete_task_for_bot(task_id)
    except Exception:
        return _format_delete_failed(requester_user_id, "Gagal menghapus task. Coba lagi nanti.")
    finally:
        pending_delete.pop(int(task_id), None)

    if not ok:
        return _format_delete_failed(requester_user_id, "Gagal menghapus task (no changes).")

    return _format_delete_success(requester_user_id, existing)


def cancelDeleteHandler(requester_user_id: str, raw_line: str) -> str:
    parts = str(raw_line or "").strip().split()
    task_id, err = _parse_task_id_arg(parts)
    if err:
        return _format_delete_failed(requester_user_id, "Gunakan: !cancel <task_id>")

    owner = pending_delete.get(int(task_id))
    if owner is None:
        return _format_delete_failed(requester_user_id, "Tidak ada request delete pending untuk ID tersebut.")

    if str(owner) != str(requester_user_id):
        return _format_delete_failed(requester_user_id, "Anda tidak berhak membatalkan delete ini.")

    pending_delete.pop(int(task_id), None)
    msg = build_box("✅  DELETE CANCELED", f"Delete untuk task ID {task_id} dibatalkan.")
    return truncate_discord(_mention_prefix(requester_user_id) + msg)


def _format_add_success(user_id: str | int | None, task_id: int, parsed: dict) -> str:
    desc = (parsed.get("description") or "").strip()

    lines = [
        f"🆔  ID        : {task_id}",
        f"📦  Project   : {parsed['project']}",
        f"🏷️  Type      : {parsed['type']}",
        f"🔥  Priority  : {str(parsed['priority']).title()}",
        f"🟢  Status    : TODO",
        f"🧠  SP        : {parsed['story_points']}",
    ]

    if desc:
        lines.extend(["", "📝  Description:", desc])

    msg = build_box("✅  TASK CREATED", "\n".join(lines))
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_list(user_id: str | int | None, header_status: str, tasks: list[dict]) -> str:
    title = "📋  TASK LIST" if not header_status else f"📋  TASK LIST ({header_status})"

    if not tasks:
        msg = build_box(title, "Tidak ada task.")
        return truncate_discord(_mention_prefix(user_id) + msg)

    rows: list[str] = []
    for idx, t in enumerate(tasks):
        tid = t.get("id")
        pr = str(t.get("priority") or "").title()
        proj = str(t.get("project") or "-")
        typ = str(t.get("type") or "-")
        status = str(t.get("status") or "")

        title_raw = str(t.get("title_raw") or "").strip()
        icon = _status_icon(status)
        label = _status_label(status)

        rows.append(f"🆔 {tid}  | 🔥 {pr} | 📦 {proj} | 🏷️ {typ}")
        rows.append(f"   {icon} {label}")
        rows.append(f"   {title_raw}")

        if idx != len(tasks) - 1:
            rows.append("")
            rows.append("──────────────────────")
            rows.append("")

    rows.append("")
    rows.append(f"Total: {len(tasks)} task(s)")

    msg = build_box(title, "\n".join(rows))
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_status_updated(user_id: str | int | None, task_id: int, new_status: str) -> str:
    body = "\n".join(
        [
            f"🆔  ID        : {task_id}",
            f"New Status    : {_status_icon(new_status)} {_status_label(new_status)}",
        ]
    )
    msg = build_box("🔄  STATUS UPDATED", body)
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_template_add(user_id: str | int | None) -> str:
    body = "\n".join(
        [
            "```txt",
            "!add",
            "project=",
            "",
            "# Choose ONE type option (delete the others):",
            "type=Task",
            "type=Story",
            "type=Bug",
            "type=Improvement",
            "",
            "# Choose ONE priority option (delete the others):",
            "priority=Low",
            "priority=Medium",
            "priority=High",
            "priority=Urgent",
            "title=",
            "sp=",
            "desc=",
            "```",
            "",
            "Notes:",
            "- type bebas (Task/Story/Bug/Improvement/dll)",
            "- priority: Low / Medium / High / Urgent",
            "- sp optional",
            "- desc optional",
        ]
    )
    msg = build_box("➕  ADD TASK TEMPLATE", body)
    return truncate_discord(_mention_prefix(user_id) + msg)


def _format_template_update(user_id: str | int | None) -> str:
    body = "\n".join(
        [
            "```txt",
            "!progress 12",
            "!done 12",
            "!todo 12",
            "```",
            "",
            "Replace 12 with task ID.",
        ]
    )
    msg = build_box("🔄  UPDATE TASK TEMPLATE", body)
    return truncate_discord(_mention_prefix(user_id) + msg)


def validateDetailInput(parts: list[str]) -> tuple[int | None, str | None]:
    if len(parts) < 2:
        return None, "Gunakan: !detail <task_id>"

    raw_id = str(parts[1] or "").strip()
    try:
        task_id = int(raw_id)
    except Exception:
        return None, "Task ID harus angka. Contoh: !detail 3"

    if task_id <= 0:
        return None, "Task ID harus angka > 0."

    return task_id, None


def fetchTaskById(task_id: int) -> dict | None:
    return get_task_for_bot(int(task_id))


def renderTaskDetail(user_id: str, task: dict) -> str:
    tid = pad_id(task.get("id"))
    project = str(task.get("project") or "-").strip() or "-"
    task_type = str(task.get("type") or "-").strip() or "-"
    title = str(task.get("title_raw") or "-").strip() or "-"
    created_at = str(task.get("created_at") or "-").strip() or "-"
    updated_at = str(task.get("updated_at") or "-").strip() or "-"

    pr_emoji, pr_label = format_priority(task.get("priority"))
    st_emoji, st_label = format_status(task.get("status"))

    status_line = f"{st_emoji} {st_label}"

    desc_raw = str(task.get("description") or "").strip()
    if not desc_raw:
        desc_block = "-"
    else:
        # keep it readable + safe for Discord length
        if len(desc_raw) > 1000:
            desc_block = truncate(desc_raw, 950) + "... (truncated)"
        else:
            desc_block = desc_raw

    completed_at = "-"
    if str(task.get("status") or "").lower() == "done":
        # No dedicated completed_at column; best-effort use updated_at.
        completed_at = updated_at if updated_at != "-" else "-"

    body_lines = [
        f"🆔 {tid}",
        f"📦 Project      : {project}",
        f"🏷️ Type         : {task_type}",
        f"{pr_emoji} Priority     : {pr_label}",
        f"📊 Status       : {status_line}",
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📝 TITLE",
        title,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📖 DESCRIPTION",
        desc_block,
        "",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━",
        f"📅 Created      : {created_at}",
        f"🛠️ Updated      : {updated_at}",
        f"✅ Completed    : {completed_at}",
    ]

    msg = build_box("📌  TASK DETAIL", "\n".join(body_lines))
    return truncate_discord(_mention_prefix(user_id) + msg)


def buildTaskDetailPayload(user_id: str, task: dict) -> dict:
    tid = pad_id(task.get("id"))
    project = str(task.get("project") or "-").strip() or "-"
    task_type = str(task.get("type") or "-").strip() or "-"
    title = str(task.get("title_raw") or "-").strip() or "-"

    pr_emoji, pr_label = format_priority(task.get("priority"))
    st_emoji, st_label = format_status(task.get("status"))
    st_label = st_label.replace("_", " ")

    desc_raw = str(task.get("description") or "").strip()
    if not desc_raw:
        desc_val = "-"
    else:
        desc_val = desc_raw
        if len(desc_val) > 1000:
            desc_val = truncate(desc_val, 997) + "... (truncated)"

    created_at_raw = str(task.get("created_at") or "-").strip() or "-"
    updated_at_raw = str(task.get("updated_at") or "-").strip() or "-"

    created = _format_dt(created_at_raw)
    updated = _format_dt(updated_at_raw)
    completed = "-"
    if str(task.get("status") or "").lower() == "done":
        completed = updated if updated != "-" else "-"

    summary = f"Project: {project} • Type: {task_type}"
    fields = [
        {"name": "Status", "value": f"{st_emoji} {st_label}", "inline": True},
        {"name": "Priority", "value": f"{pr_emoji} {pr_label}", "inline": True},
        {"name": "Description", "value": desc_val, "inline": False},
        {"name": "Created", "value": created, "inline": True},
        {"name": "Updated", "value": updated, "inline": True},
        {"name": "Completed", "value": completed, "inline": True},
    ]

    title_trim = title
    if len(title_trim) > 100:
        title_trim = truncate(title_trim, 100)

    embed = buildEmbed(
        title=f"📌 Task #{tid} — {title_trim}",
        description=summary,
        color=_priority_color(task.get("priority")),
        fields=fields,
        footer=f"Task ID: {tid}",
        timestamp=created_at_raw if created_at_raw != "-" else None,
    )

    return _build_message_payload(user_id=user_id, content=f"<@{user_id}>" if user_id else None, embeds=[embed])


def parseListCommand(raw_line: str) -> tuple[str | None, str | None, str | None]:
    parts = str(raw_line or "").strip().split()
    if len(parts) < 2:
        return None, None, "Scope tidak dikenali. Gunakan: all | active | todo | progress | done"

    scope = str(parts[1] or "").strip().lower()
    keyword = None
    if len(parts) >= 3:
        keyword = str(parts[2] or "").strip()
        if not keyword:
            keyword = None

    valid = {"all", "active", "todo", "progress", "done"}
    if scope not in valid:
        return None, None, "Scope tidak dikenali. Gunakan: all | active | todo | progress | done"

    return scope, keyword, None


def buildListQuery(scope: str, keyword: str | None) -> tuple[str, str | None, int]:
    # Query building is encapsulated in DB layer; we keep this wrapper for structure clarity.
    return str(scope), (str(keyword) if keyword is not None else None), 20


def executeTaskQuery(scope: str, keyword: str | None, limit: int) -> tuple[list[dict], int]:
    return search_tasks_for_bot(scope=scope, keyword=keyword, limit=int(limit), offset=0)


def renderTaskListEmbed(
    *,
    user_id: str,
    scope_title: str,
    scope_norm: str,
    keyword: str | None,
    tasks: list[dict],
    total_matches: int,
    limit: int,
) -> list[dict]:
    kw = str(keyword or "").strip()

    if total_matches <= 0:
        desc = f"Tidak ada task yang cocok dengan pencarian \"{kw}\"" if kw else "Tidak ada task untuk scope tersebut."
        embed = buildEmbed(
            title="🔍 No Task Found",
            description=desc,
            color=NEUTRAL_LIST_COLOR,
            fields=[],
            footer=None,
            timestamp=None,
        )
        return [_build_message_payload(user_id=user_id, content=f"<@{user_id}>" if user_id else None, embeds=[embed])]

    shown_count = min(int(limit), int(total_matches))

    chunks: list[list[dict]] = []
    chunk_size = 10
    for i in range(0, len(tasks), chunk_size):
        chunks.append(tasks[i : i + chunk_size])
    if not chunks:
        chunks = [[]]

    payloads: list[dict] = []
    for idx, ch in enumerate(chunks):
        payloads.append(
            _build_list_embeds(
                user_id=user_id,
                title=scope_title,
                kind_norm=scope_norm,
                keyword=kw,
                tasks=ch,
                total_matches=total_matches,
                shown_count=shown_count,
                chunk_index=idx,
                chunk_count=len(chunks),
            )
        )

    return payloads


def detailCommandHandler(requester_user_id: str, raw_line: str) -> str:
    parts = str(raw_line or "").strip().split()
    task_id, err = validateDetailInput(parts)
    if err:
        msg = build_box("⚠️  TASK NOT FOUND", err)
        return truncate_discord(_mention_prefix(requester_user_id) + msg)

    task = fetchTaskById(int(task_id))
    if task is None:
        msg = build_box("⚠️  TASK NOT FOUND", f"Task dengan ID {task_id} tidak ditemukan.")
        return truncate_discord(_mention_prefix(requester_user_id) + msg)

    # Embed-style detail
    return buildTaskDetailPayload(requester_user_id, task)


def _build_list_embeds(
    *,
    user_id: str,
    title: str,
    kind_norm: str,
    keyword: str | None,
    tasks: list[dict],
    total_matches: int,
    shown_count: int,
    chunk_index: int,
    chunk_count: int,
) -> dict:
    total = int(total_matches)

    fields: list[dict] = []
    for t in tasks:
        tid = pad_id(t.get("id"))
        pr_emoji, pr_label = format_priority(t.get("priority"))
        st_emoji, st_label = format_status(t.get("status"))
        st_label = st_label.replace("_", " ")
        name = f"#{tid} • {pr_emoji} {pr_label} • {st_emoji} {st_label}"

        proj = truncate(str(t.get("project") or "-"), 30)
        ttitle = truncate(str(t.get("title_raw") or "-"), 80)
        value = "\n".join([f"📦 {proj}", ttitle])
        fields.append({"name": name, "value": value, "inline": False})

    footer = f"Showing {shown_count} of {total} results" if total > shown_count else f"Total: {total} task(s)"
    if chunk_count > 1:
        footer = footer + f" • Part {chunk_index + 1}/{chunk_count}"

    kw = str(keyword or "").strip()
    title_suffix = f" — Search: \"{kw}\"" if kw else ""

    embed = buildEmbed(
        title=f"📋 Task List ({title}){title_suffix}",
        description=f"Total: {total} tasks found",
        color=NEUTRAL_LIST_COLOR,
        fields=fields,
        footer=footer,
        timestamp=None,
    )

    return _build_message_payload(user_id=user_id, content=f"<@{user_id}>" if user_id else None, embeds=[embed])


def run_polling_bot() -> None:
    """Run the polling loop."""

    logger = _setup_logger()
    token, channel_id, user_id = _get_credentials()

    if not token or not channel_id or not user_id:
        print("Missing DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID / DISCORD_USER_ID (env or .env).")
        return

    # Startup report (send once per process start)
    try:
        payloads = build_startup_report_payloads(user_id)
        _reply_many(channel_id, token, payloads, logger)
    except Exception as e:
        logger.exception("Failed sending startup report: %s", e)

    last_processed_id = _read_last_message_id()
    logger.info("Starting bot listener. last_processed_id=%s", last_processed_id)

    messages_url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=20"

    while True:
        try:
            data = _http_get_json(messages_url, token, logger)
            if not isinstance(data, list):
                _sleep_seconds(5)
                continue

            new_messages: list[tuple[int, str, str]] = []
            for msg in data:
                try:
                    msg_id = int(msg.get("id") or 0)
                except (TypeError, ValueError):
                    continue

                if msg_id <= last_processed_id:
                    continue

                author = msg.get("author") or {}
                if bool(author.get("bot")):
                    continue

                author_id = str(author.get("id") or "")
                if not author_id:
                    continue

                content = str(msg.get("content") or "")

                cmd = content.strip().lower()
                if not (
                    cmd.startswith("!add")
                    or cmd.startswith("!help")
                    or cmd.startswith("!list")
                    or cmd.startswith("!detail")
                    or cmd.startswith("!delete")
                    or cmd.startswith("!confirm")
                    or cmd.startswith("!cancel")
                    or cmd.startswith("!progress")
                    or cmd.startswith("!done")
                    or cmd.startswith("!todo")
                    or cmd.startswith("!template")
                ):
                    continue

                new_messages.append((msg_id, author_id, content))

            new_messages.sort(key=lambda x: x[0])

            for msg_id, author_id, content in new_messages:
                try:
                    raw = str(content or "").strip()
                    cmd_line = raw.splitlines()[0].strip().lower() if raw else ""

                    if cmd_line == "!help":
                        _reply(channel_id, token, _format_help(author_id), logger)
                    elif cmd_line.startswith("!template"):
                        parts = cmd_line.split()
                        if len(parts) != 2:
                            _reply(channel_id, token, _format_error(user_id), logger)
                        else:
                            arg = parts[1].strip().lower()
                            if arg == "add":
                                _reply(channel_id, token, _format_template_add(user_id), logger)
                            elif arg == "update":
                                _reply(channel_id, token, _format_template_update(user_id), logger)
                            else:
                                _reply(channel_id, token, _format_error(user_id), logger)
                    elif cmd_line.startswith("!list"):
                        scope, keyword, err = parseListCommand(cmd_line)
                        if err or not scope:
                            embed = buildEmbed(
                                title="⚠️ Invalid Scope",
                                description=str(err or "Scope tidak dikenali. Gunakan: all | active | todo | progress | done"),
                                color=15158332,
                                fields=[],
                                footer=None,
                                timestamp=None,
                            )
                            _reply(
                                channel_id,
                                token,
                                _build_message_payload(
                                    user_id=author_id,
                                    content=f"<@{author_id}>",
                                    embeds=[embed],
                                ),
                                logger,
                            )
                        else:
                            scope_q, keyword_q, limit = buildListQuery(scope, keyword)
                            rows, total = executeTaskQuery(scope_q, keyword_q, limit)

                            scope_title = scope_q.upper() if scope_q != "progress" else "PROGRESS"
                            payloads = renderTaskListEmbed(
                                user_id=author_id,
                                scope_title=scope_title,
                                scope_norm=scope_q,
                                keyword=keyword_q,
                                tasks=rows,
                                total_matches=total,
                                limit=limit,
                            )
                            _reply_many(channel_id, token, payloads, logger)
                    elif cmd_line.startswith("!detail"):
                        msg = detailCommandHandler(author_id, cmd_line)
                        _reply(channel_id, token, msg, logger)
                    elif cmd_line.startswith("!delete"):
                        msg = deleteCommandHandler(author_id, cmd_line)
                        _reply(channel_id, token, msg, logger)
                    elif cmd_line.startswith("!confirm"):
                        msg = confirmDeleteHandler(author_id, cmd_line)
                        _reply(channel_id, token, msg, logger)
                    elif cmd_line.startswith("!cancel"):
                        msg = cancelDeleteHandler(author_id, cmd_line)
                        _reply(channel_id, token, msg, logger)
                    elif cmd_line.startswith("!progress") or cmd_line.startswith("!done") or cmd_line.startswith("!todo"):
                        parts = cmd_line.split()
                        if len(parts) != 2:
                            _reply(channel_id, token, _format_error(user_id), logger)
                        else:
                            action = parts[0]
                            task_id_raw = parts[1]
                            try:
                                task_id = int(task_id_raw)
                            except Exception:
                                _reply(channel_id, token, _format_error(user_id), logger)
                            else:
                                existing = get_task_for_bot(task_id)
                                if existing is None:
                                    _reply(channel_id, token, _format_error(user_id), logger)
                                else:
                                    new_status = "todo"
                                    if action == "!progress":
                                        new_status = "in_progress"
                                    elif action == "!done":
                                        new_status = "done"
                                    elif action == "!todo":
                                        new_status = "todo"

                                    updated = update_task_status_for_bot(task_id=task_id, status=new_status)
                                    if updated <= 0:
                                        _reply(channel_id, token, _format_error(user_id), logger)
                                    else:
                                        _reply(
                                            channel_id,
                                            token,
                                            _format_status_updated(user_id, task_id, new_status),
                                            logger,
                                        )
                    elif cmd_line == "!add":
                        parsed = parse_add_command(raw)
                        if parsed is None:
                            _reply(channel_id, token, _format_error(user_id), logger)
                        else:
                            task_id = insert_task(
                                project=parsed["project"],
                                task_type=parsed["type"],
                                title=parsed["title"],
                                priority=parsed["priority"],
                                story_points=int(parsed["story_points"]),
                                description=parsed.get("description"),
                            )
                            _reply(
                                channel_id,
                                token,
                                _format_add_success(user_id, task_id, parsed),
                                logger,
                            )
                    else:
                        _reply(channel_id, token, _format_error(author_id), logger)
                except Exception as e:
                    logger.exception("Failed processing command: %s", e)
                    body = "Gagal memproses perintah. Coba lagi nanti."
                    _reply(channel_id, token, truncate_discord(_mention_prefix(author_id) + build_box("❌  ERROR", body)), logger)

                last_processed_id = msg_id
                _write_last_message_id(last_processed_id)

        except Exception as e:
            logger.exception("Loop error: %s", e)

        _sleep_seconds(5)
