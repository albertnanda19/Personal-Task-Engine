"""CLI entrypoint for personal_task_engine."""

import sys

from database.schema import init_db


def main(argv: list[str] | None = None) -> int:
    """Initialize DB and run CLI."""

    argv = argv or []

    if argv[:1] == ["run-bot"]:
        init_db()
        try:
            from app.bot_listener import run_polling_bot

            run_polling_bot()
        except KeyboardInterrupt:
            print("Bot stopped.")
        return 0

    if argv[:1] == ["db"]:
        from cli.commands import run_cli

        return run_cli(argv)

    init_db()

    from cli.commands import run_cli

    return run_cli(argv)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
