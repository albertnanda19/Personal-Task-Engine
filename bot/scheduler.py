"""Legacy scheduler placeholder.

The project previously contained an 08:00 daily scheduler loop.
Phase 9 replaces this with a startup-only catch-up report.
"""


def run_daily_scheduler() -> None:
    """Deprecated: no-op for backward compatibility."""

    print("Scheduler is deprecated. Use: python3 main.py run-bot")
