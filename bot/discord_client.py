"""Minimal Discord REST client using urllib.

Constraints:
- Standard library only
- Synchronous
- Plain text messages only

Environment variables:
- DISCORD_BOT_TOKEN
- DISCORD_CHANNEL_ID

A minimal .env loader is included to support local development.
"""

import json
import os
from datetime import datetime, timezone
import urllib.request


_ENV_FILENAME = ".env"


def load_env() -> None:
    """Load environment variables from .env in the project root.

    This is a tiny loader (not python-dotenv). It:
    - ignores blank lines and comments (#...)
    - parses KEY=VALUE
    - strips surrounding single/double quotes
    - does not override variables already set in the environment
    """

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env_path = os.path.join(project_root, _ENV_FILENAME)
    if not os.path.exists(env_path):
        return

    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.read().splitlines()

        for raw_line in lines:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue

            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip("\"").strip("'")

            if not key:
                continue
            if key in os.environ:
                continue

            os.environ[key] = value
    except OSError as exc:
        print(f"Failed to read .env: {exc}")


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _sleep_seconds(seconds: float) -> None:
    seconds = float(seconds)
    if seconds <= 0:
        return
    end = _utc_now().timestamp() + seconds
    while _utc_now().timestamp() < end:
        pass


def _get_credentials() -> tuple[str | None, str | None]:
    token = os.environ.get("DISCORD_BOT_TOKEN")
    channel_id = os.environ.get("DISCORD_CHANNEL_ID")
    return token, channel_id


def send_message(content: str) -> bool:
    """Send a plain text message to the configured Discord channel.

    Returns True on success, False on failure.
    """

    load_env()
    token, channel_id = _get_credentials()

    if not token or not channel_id:
        print(
            "Missing Discord credentials. Set DISCORD_BOT_TOKEN and DISCORD_CHANNEL_ID (env or .env)."
        )
        return False

    url = f"https://discord.com/api/v10/channels/{channel_id}/messages"
    payload = json.dumps({"content": content}).encode("utf-8")

    user_agent = "personal_task_engine/1.0 (+https://github.com/)"

    def _attempt() -> tuple[bool, int | None, dict | None, str | None]:
        req = urllib.request.Request(
            url,
            data=payload,
            method="POST",
            headers={
                "Authorization": f"Bot {token}",
                "Content-Type": "application/json",
                "Accept": "application/json",
                "User-Agent": user_agent,
            },
        )

        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status = int(getattr(resp, "status", 200))
                body = resp.read().decode("utf-8", errors="replace")
                data = None
                if body:
                    try:
                        data = json.loads(body)
                    except json.JSONDecodeError:
                        data = None

                return 200 <= status < 300, status, data, body
        except Exception as e:
            print(f"Discord request failed: {e}")
            return False, None, None, None

    ok, status, data, body = _attempt()
    if ok:
        return True

    # Without urllib.error, we cannot reliably inspect HTTP status codes.
    # Best-effort fallback: if Discord returns a JSON body that includes retry_after, wait and retry once.
    if isinstance(data, dict) and data.get("retry_after") is not None:
        try:
            retry_after = float(data.get("retry_after") or 0)
        except (TypeError, ValueError):
            retry_after = 0
        _sleep_seconds(retry_after if retry_after > 0 else 1)

        ok2, _status2, _data2, _body2 = _attempt()
        if ok2:
            return True

    if body:
        body_preview = body if len(body) <= 800 else body[:800] + "..."
        print(body_preview)
    return False
