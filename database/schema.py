"""Database schema initialization and lightweight migrations."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from database.connection import get_connection


@dataclass(frozen=True)
class MigrationStatus:
    """Status info for migrations."""

    applied: list[str]
    pending: list[str]


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def ensure_migrations_table() -> None:
    """Create migrations table if it doesn't exist."""

    with get_connection() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS migrations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                name TEXT NOT NULL UNIQUE,
                applied_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def _migrations_dir() -> Path:
    return Path(__file__).resolve().parent / "migrations"


def _list_migration_files() -> list[Path]:
    migrations_dir = _migrations_dir()
    if not migrations_dir.exists():
        return []

    files = [p for p in migrations_dir.iterdir() if p.is_file() and p.suffix == ".sql"]
    files.sort(key=lambda p: p.name)
    return files


def _get_applied_migration_names() -> list[str]:
    with get_connection() as conn:
        cur = conn.execute("SELECT name FROM migrations ORDER BY name ASC")
        return [str(r[0]) for r in cur.fetchall()]


def run_migrations() -> list[str]:
    """Apply pending migrations.

    Returns a list of migration names applied during this run.

    Behavior:
    - Migration files are read from database/migrations/*.sql
    - Sorted by filename
    - Each migration is applied at most once (tracked in migrations table)
    - Commits after each migration
    - Rollback on error
    """

    ensure_migrations_table()
    migration_files = _list_migration_files()
    applied = set(_get_applied_migration_names())

    applied_now: list[str] = []
    for path in migration_files:
        name = path.name
        if name in applied:
            continue

        sql = path.read_text(encoding="utf-8")
        with get_connection() as conn:
            try:
                conn.execute("BEGIN")
                conn.executescript(sql)
                conn.execute(
                    "INSERT INTO migrations(name, applied_at) VALUES (?, ?)",
                    (name, _utc_now_iso()),
                )
                conn.commit()
            except Exception:
                conn.rollback()
                raise

        applied_now.append(name)

    return applied_now


def get_migration_status() -> MigrationStatus:
    """Return lists of applied and pending migrations."""

    ensure_migrations_table()
    applied = _get_applied_migration_names()
    migration_files = _list_migration_files()
    all_names = [p.name for p in migration_files]
    pending = [name for name in all_names if name not in set(applied)]
    return MigrationStatus(applied=applied, pending=pending)


def init_db() -> None:
    """Initialize the database schema.

    Phase 1 compatibility wrapper: runs migrations.
    """

    run_migrations()
