"""CLI entrypoint for personal_task_engine."""

from __future__ import annotations

import sys

from cli.commands import run_cli
from database.schema import init_db


def main(argv: list[str] | None = None) -> int:
    """Initialize DB and run CLI."""

    init_db()
    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
