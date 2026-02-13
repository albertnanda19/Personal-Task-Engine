"""CLI entrypoint for personal_task_engine."""

from __future__ import annotations

import sys

from cli.commands import run_cli
from bot.scheduler import run_daily_scheduler
from database.schema import init_db


def main(argv: list[str] | None = None) -> int:
    """Initialize DB and run CLI."""

    argv = argv or []

    if argv[:1] == ["db"]:
        return run_cli(argv)

    init_db()

    if len(argv) >= 2 and argv[0] == "bot" and argv[1] == "run":
        try:
            run_daily_scheduler()
        except KeyboardInterrupt:
            print("Scheduler stopped.")
        return 0

    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
