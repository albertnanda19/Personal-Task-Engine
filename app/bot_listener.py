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

from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from app.commands import parse_add_command
from app.db import insert_task
from bot.discord_client import load_env


def _setup_logger() -> logging.Logger:
    logs_dir = Path(__file__).resolve().parent.parent / "logs"
    logs_dir.mkdir(parents=True, exist_ok=True)

    logger = logging.getLogger("bot_listener")
    logger.setLevel(logging.INFO)

    if not any(isinstance(h, logging.FileHandler) for h in logger.handlers):
        fh = logging.FileHandler(logs_dir / "bot.log")
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        fh.setFormatter(fmt)
        logger.addHandler(fh)

    return logger


def _get_credentials() -> tuple[str | None, str | None]:
    load_env()
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    return token, channel_id


def _data_dir() -> Path:
    d = Path(__file__).resolve().parent.parent / "data"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _last_id_path() -> Path:
    return _data_dir() / "last_message_id.txt"


def _read_last_message_id() -> int:
    path = _last_id_path()
    if not path.exists():
        return 0
    try:
        raw = path.read_text(encoding="utf-8").strip()
        return int(raw) if raw else 0
    except Exception:
        return 0


def _write_last_message_id(message_id: int) -> None:
    _last_id_path().write_text(str(int(message_id)), encoding="utf-8")


def _http_get_json(url: str, token: str, logger: logging.Logger) -> Any:
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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        logger.error("HTTP GET error status=%s body=%s", e.code, body[:800])
        return None
    except urllib.error.URLError as e:
        logger.error("HTTP GET URLError: %s", e)
        return None
    except Exception as e:
        logger.exception("HTTP GET unexpected error: %s", e)
        return None


def _http_post_json(url: str, token: str, payload: dict[str, Any], logger: logging.Logger) -> bool:
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
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace") if hasattr(e, "read") else ""
        logger.error("HTTP POST error status=%s body=%s", e.code, body[:800])
        return False
    except urllib.error.URLError as e:
        logger.error("HTTP POST URLError: %s", e)
        return False
    except Exception as e:
        logger.exception("HTTP POST unexpected error: %s", e)
        return False


def _reply(channel_id: str, token: str, content: str, logger: logging.Logger) -> None:
    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    _http_post_json(url, token, {"content": content}, logger)


def run_polling_bot() -> None:
    """Run the polling loop."""

    logger = _setup_logger()
    token, channel_id = _get_credentials()

    if not token or not channel_id:
        print("Missing DISCORD_BOT_TOKEN / DISCORD_CHANNEL_ID (env or .env).")
        return

    last_processed_id = _read_last_message_id()
    logger.info("Starting bot listener. last_processed_id=%s", last_processed_id)

    messages_url = (
        f"https://discord.com/api/v10/channels/{channel_id}/messages?"
        + urllib.parse.urlencode({"limit": "20"})
    )

    while True:
        try:
            data = _http_get_json(messages_url, token, logger)
            if not isinstance(data, list):
                time.sleep(5)
                continue

            new_messages = []
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
                if not content.strip().lower().startswith("!add"):
                    continue

                new_messages.append((msg_id, content))

            new_messages.sort(key=lambda x: x[0])

            for msg_id, content in new_messages:
                parsed = parse_add_command(content)
                if parsed is None:
                    _reply(
                        channel_id,
                        token,
                        "❌ Format salah.\nGunakan: !add | Priority | Title | DueDate | StoryPoint",
                        logger,
                    )
                    last_processed_id = msg_id
                    _write_last_message_id(last_processed_id)
                    continue

                try:
                    task_id = insert_task(
                        title=parsed["title"],
                        priority=parsed["priority"],
                        story_points=int(parsed["story_points"]),
                        due_date=parsed.get("due_date"),
                    )

                    due_display = parsed.get("due_date") or "-"
                    reply_text = (
                        f"✅ Task berhasil dibuat (ID: {task_id})\n"
                        f"Title: {parsed['title']}\n"
                        f"Priority: {parsed['priority']}\n"
                        f"Due: {due_display}\n"
                        f"Story Points: {parsed['story_points']}"
                    )
                    _reply(channel_id, token, reply_text, logger)
                except Exception as e:
                    logger.exception("Failed processing add command: %s", e)
                    _reply(
                        channel_id,
                        token,
                        "❌ Gagal menyimpan task. Coba lagi nanti.",
                        logger,
                    )

                last_processed_id = msg_id
                _write_last_message_id(last_processed_id)

        except Exception as e:
            logger.exception("Loop error: %s", e)

        time.sleep(5)
