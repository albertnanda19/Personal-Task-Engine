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
    get_task_for_bot,
    insert_task,
    list_tasks_for_bot,
    list_tasks_paginated_for_bot,
    update_task_status_for_bot,
)
from app.list_renderer import render_task_list
from app.startup_report import build_startup_report_message
from app.ui import build_box, truncate_discord
from bot.discord_client import load_env


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


def _reply(channel_id: str, token: str, content: str, logger: logging.Logger) -> None:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    _http_post_json(url, token, {"content": content}, logger)


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
            "!list all",
            "```",
            "```txt",
            "!list todo",
            "```",
            "```txt",
            "!list progress",
            "```",
            "```txt",
            "!list done",
            "```",
            "",
            "🔄 Update:",
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


def run_polling_bot() -> None:
    """Run the polling loop."""

    logger = _setup_logger()
    token, channel_id, user_id = _get_credentials()

    if not token or not channel_id or not user_id:
        print("Missing DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID / DISCORD_USER_ID (env or .env).")
        return

    # Startup report (send once per process start)
    try:
        report = build_startup_report_message()
        _reply(channel_id, token, report, logger)
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

            new_messages: list[tuple[int, str]] = []
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

                content = str(msg.get("content") or "")

                cmd = content.strip().lower()
                if not (
                    cmd.startswith("!add")
                    or cmd.startswith("!help")
                    or cmd.startswith("!list")
                    or cmd.startswith("!progress")
                    or cmd.startswith("!done")
                    or cmd.startswith("!todo")
                    or cmd.startswith("!template")
                ):
                    continue

                new_messages.append((msg_id, content))

            new_messages.sort(key=lambda x: x[0])

            for msg_id, content in new_messages:
                try:
                    raw = str(content or "").strip()
                    cmd_line = raw.splitlines()[0].strip().lower() if raw else ""

                    if cmd_line == "!help":
                        _reply(channel_id, token, _format_help(user_id), logger)
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
                        parts = cmd_line.split()
                        if len(parts) not in (2, 3):
                            _reply(channel_id, token, _format_error(user_id), logger)
                        else:
                            kind = parts[1].strip().lower()
                            page = 1
                            if len(parts) == 3:
                                try:
                                    page = int(parts[2])
                                except Exception:
                                    page = 1

                            # Normalize kinds/aliases
                            if kind == "progress":
                                kind_norm = "progress"
                                title = "PROGRESS"
                            elif kind == "in_progress":
                                kind_norm = "progress"
                                title = "PROGRESS"
                            elif kind == "all":
                                kind_norm = "all"
                                title = "ALL"
                            elif kind == "active":
                                kind_norm = "active"
                                title = "ACTIVE"
                            elif kind == "done":
                                kind_norm = "done"
                                title = "DONE"
                            elif kind == "today":
                                kind_norm = "today"
                                title = "TODAY"
                            elif kind == "todo":
                                kind_norm = "todo"
                                title = "TODO"
                            else:
                                _reply(channel_id, token, _format_error(user_id), logger)
                                kind_norm = ""
                                title = ""

                            if kind_norm:
                                tasks, meta = list_tasks_paginated_for_bot(
                                    kind=kind_norm,
                                    page=page,
                                    page_size=15,
                                )

                                group = bool(kind_norm == "all" and int(meta.get("total_kind") or 0) > 5)

                                total_label = None
                                if title == "ACTIVE":
                                    total_label = "Total Active"
                                elif title == "DONE":
                                    total_label = "Total Completed"
                                elif title == "TODAY":
                                    total_label = "Total Today"
                                elif title == "TODO":
                                    total_label = "Total Todo"
                                elif title == "PROGRESS":
                                    total_label = "Total In Progress"

                                rendered = render_task_list(
                                    tasks=tasks,
                                    title=title,
                                    group_by_status=group,
                                    page=int(meta.get("page") or 1),
                                    page_size=int(meta.get("page_size") or 15),
                                    total_active=int(meta.get("total_active") or 0)
                                    if title in ("ALL", "ACTIVE")
                                    else None,
                                    total_completed=int(meta.get("total_completed") or 0)
                                    if title in ("ALL", "DONE")
                                    else None,
                                    total_all=int(meta.get("total_all") or 0) if title == "ALL" else None,
                                    total_label=total_label,
                                    total_value=int(meta.get("total_kind") or 0),
                                    kind_for_hint=kind_norm,
                                )

                                msg = truncate_discord(_mention_prefix(user_id) + rendered)
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
                        _reply(channel_id, token, _format_error(user_id), logger)
                except Exception as e:
                    logger.exception("Failed processing command: %s", e)
                    body = "Gagal memproses perintah. Coba lagi nanti."
                    _reply(channel_id, token, truncate_discord(_mention_prefix(user_id) + build_box("❌  ERROR", body)), logger)

                last_processed_id = msg_id
                _write_last_message_id(last_processed_id)

        except Exception as e:
            logger.exception("Loop error: %s", e)

        _sleep_seconds(5)
