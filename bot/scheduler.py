"""Simple daily scheduler.

Phase 4: Synchronous loop that sends the dashboard summary once a day at 08:00.
"""

from __future__ import annotations

import time
from datetime import date, datetime

from bot.discord_client import send_message
from services.summary_service import get_dashboard_summary


def _format_dashboard_message(summary: dict) -> str:
    avg = float(summary.get("average_execution_score") or 0)
    lines = [
        "PERSONAL TASK DASHBOARD",
        "-----------------------",
        f"Todo: {summary.get('total_todo', 0)}",
        f"Doing: {summary.get('total_doing', 0)}",
        f"Done: {summary.get('total_done', 0)}",
        f"Overdue: {summary.get('total_overdue', 0)}",
        f"Average Score: {avg:.1f}",
    ]
    return "\n".join(lines)


def run_daily_scheduler() -> None:
    """Run an infinite loop that sends daily summary at 08:00 local time."""

    last_sent_date: date | None = None

    while True:
        now = datetime.now()

        if last_sent_date is not None and now.date() != last_sent_date:
            last_sent_date = None

        if now.hour == 8 and now.minute == 0:
            if last_sent_date != now.date():
                summary = get_dashboard_summary()
                message = _format_dashboard_message(summary)
                send_message(message)
                last_sent_date = now.date()

        time.sleep(60)
