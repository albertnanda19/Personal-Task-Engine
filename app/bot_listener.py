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
from app.db import get_task_for_bot, insert_task, list_tasks_for_bot, update_task_status_for_bot
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


def _get_credentials() -> tuple[str | None, str | None]:
    load_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    return token, channel_id


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
    return f"<@{user_id}>\n"


def _sep() -> str:
    return "=========================="


def _format_help(user_id: str | int | None) -> str:
    msg = "\n".join(
        [
            _sep(),
            "📘 TASK BOT DOCUMENTATION",
            _sep(),
            "",
            "➕ Add Task:",
            "!add",
            "project=ProjectName",
            "type=Bug",
            "priority=High",
            "title=Short Title",
            "sp=3",
            "desc=Optional description",
            "",
            "📋 List:",
            "!list all",
            "!list todo",
            "!list progress",
            "!list done",
            "",
            "🔄 Update Status:",
            "!progress 12",
            "!done 12",
            "!todo 12",
            "",
            _sep(),
        ]
    )
    return _mention_prefix(user_id) + msg


def _format_error(user_id: str | int | None) -> str:
    msg = "\n".join(
        [
            _sep(),
            "❌ FORMAT ERROR",
            _sep(),
            "",
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
    return _mention_prefix(user_id) + msg


def _format_add_success(user_id: str | int | None, task_id: int, parsed: dict) -> str:
    msg = "\n".join(
        [
            _sep(),
            "✅ SUCCESS",
            _sep(),
            "",
            f"Task berhasil dibuat (ID: {task_id})",
            f"Project: {parsed['project']}",
            f"Type: {parsed['type']}",
            f"Priority: {str(parsed['priority']).title()}",
            f"Title: {parsed['title']}",
            f"SP: {parsed['story_points']}",
        ]
    )
    return _mention_prefix(user_id) + msg


def _status_label(status: str) -> str:
    s = str(status or "").lower()
    if s == "todo":
        return "TODO"
    if s == "in_progress":
        return "IN_PROGRESS"
    if s == "done":
        return "DONE"
    return s.upper() or "-"


def _format_list(user_id: str | int | None, status_label: str, tasks: list[dict]) -> str:
    header = "📋 TASK LIST (" + status_label + ")"
    lines = [_sep(), header, _sep(), ""]
    if not tasks:
        lines.append("Tidak ada task.")
        return _mention_prefix(user_id) + "\n".join(lines)

    for t in tasks:
        lines.extend(
            [
                f"[ID: {t.get('id')}] [{str(t.get('priority') or '').title()}] [{t.get('project')}] [{t.get('type')}]",
                f"Title: {t.get('title_raw')}",
                f"SP: {t.get('story_points', 0)}",
                f"Status: {_status_label(t.get('status'))}",
                "--------------------------",
            ]
        )
    return _mention_prefix(user_id) + "\n".join(lines)


def _format_status_updated(user_id: str | int | None, task_id: int, new_status: str) -> str:
    msg = "\n".join(
        [
            _sep(),
            "🔄 STATUS UPDATED",
            _sep(),
            "",
            f"Task ID: {task_id}",
            f"New Status: {_status_label(new_status)}",
        ]
    )
    return _mention_prefix(user_id) + msg


def run_polling_bot() -> None:
    """Run the polling loop."""

    logger = _setup_logger()
    token, channel_id = _get_credentials()

    if not token or not channel_id:
        print("Missing DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID (env or .env).")
        return

    last_processed_id = _read_last_message_id()
    logger.info("Starting bot listener. last_processed_id=%s", last_processed_id)

    messages_url = f"https://discord.com/api/v10/channels/{channel_id}/messages?limit=20"

    while True:
        try:
            data = _http_get_json(messages_url, token, logger)
            if not isinstance(data, list):
                _sleep_seconds(5)
                continue

            new_messages: list[tuple[int, str, str | None]] = []
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

                author_id = author.get("id")

                content = str(msg.get("content") or "")

                cmd = content.strip().lower()
                if not (
                    cmd.startswith("!add")
                    or cmd.startswith("!help")
                    or cmd.startswith("!list")
                    or cmd.startswith("!progress")
                    or cmd.startswith("!done")
                    or cmd.startswith("!todo")
                ):
                    continue

                new_messages.append((msg_id, content, str(author_id) if author_id is not None else None))

            new_messages.sort(key=lambda x: x[0])

            for msg_id, content, author_id in new_messages:
                try:
                    raw = str(content or "").strip()
                    cmd_line = raw.splitlines()[0].strip().lower() if raw else ""

                    if cmd_line == "!help":
                        _reply(channel_id, token, _format_help(author_id), logger)
                    elif cmd_line.startswith("!list"):
                        parts = cmd_line.split()
                        if len(parts) != 2:
                            _reply(channel_id, token, _format_error(author_id), logger)
                        else:
                            arg = parts[1].strip().lower()
                            if arg == "all":
                                tasks = list_tasks_for_bot(status=None, limit=20)
                                _reply(channel_id, token, _format_list(author_id, "ALL", tasks), logger)
                            elif arg == "todo":
                                tasks = list_tasks_for_bot(status="todo", limit=20)
                                _reply(channel_id, token, _format_list(author_id, "TODO", tasks), logger)
                            elif arg == "progress":
                                tasks = list_tasks_for_bot(status="in_progress", limit=20)
                                _reply(
                                    channel_id, token, _format_list(author_id, "IN_PROGRESS", tasks), logger
                                )
                            elif arg == "done":
                                tasks = list_tasks_for_bot(status="done", limit=20)
                                _reply(channel_id, token, _format_list(author_id, "DONE", tasks), logger)
                            else:
                                _reply(channel_id, token, _format_error(author_id), logger)
                    elif cmd_line.startswith("!progress") or cmd_line.startswith("!done") or cmd_line.startswith("!todo"):
                        parts = cmd_line.split()
                        if len(parts) != 2:
                            _reply(channel_id, token, _format_error(author_id), logger)
                        else:
                            action = parts[0]
                            task_id_raw = parts[1]
                            try:
                                task_id = int(task_id_raw)
                            except Exception:
                                _reply(channel_id, token, _format_error(author_id), logger)
                            else:
                                existing = get_task_for_bot(task_id)
                                if existing is None:
                                    _reply(channel_id, token, _format_error(author_id), logger)
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
                                        _reply(channel_id, token, _format_error(author_id), logger)
                                    else:
                                        _reply(
                                            channel_id,
                                            token,
                                            _format_status_updated(author_id, task_id, new_status),
                                            logger,
                                        )
                    elif cmd_line == "!add":
                        parsed = parse_add_command(raw)
                        if parsed is None:
                            _reply(channel_id, token, _format_error(author_id), logger)
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
                                _format_add_success(author_id, task_id, parsed),
                                logger,
                            )
                    else:
                        _reply(channel_id, token, _format_error(author_id), logger)
                except Exception as e:
                    logger.exception("Failed processing command: %s", e)
                    _reply(
                        channel_id,
                        token,
                        _mention_prefix(author_id)
                        + "\n".join(
                            [
                                _sep(),
                                "❌ ERROR",
                                _sep(),
                                "",
                                "Gagal memproses perintah. Coba lagi nanti.",
                            ]
                        ),
                        logger,
                    )

                last_processed_id = msg_id
                _write_last_message_id(last_processed_id)

        except Exception as e:
            logger.exception("Loop error: %s", e)

        _sleep_seconds(5)
