"""Database schema initialization and lightweight migrations."""

from datetime import datetime, timezone
import os

from database.connection import get_connection


class MigrationStatus:
    """Status info for migrations."""

    def __init__(self, applied: list[str], pending: list[str]) -> None:
        self.applied = applied
        self.pending = pending


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


def _migrations_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(here, "migrations")


def _list_migration_files() -> list[str]:
    migrations_dir = _migrations_dir()
    if not os.path.isdir(migrations_dir):
        return []

    files: list[str] = []
    for name in os.listdir(migrations_dir):
        if not name.lower().endswith(".sql"):
            continue
        full = os.path.join(migrations_dir, name)
        if os.path.isfile(full):
            files.append(full)

    files.sort(key=lambda p: os.path.basename(p))
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
        name = os.path.basename(path)
        if name in applied:
            continue

        with open(path, "r", encoding="utf-8") as f:
            sql = f.read()
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
    all_names = [os.path.basename(p) for p in migration_files]
    pending = [name for name in all_names if name not in set(applied)]
    return MigrationStatus(applied=applied, pending=pending)


def init_db() -> None:
    """Initialize the database schema.

    Phase 1 compatibility wrapper: runs migrations.
    """

    run_migrations()
    _ensure_tasks_phase7_columns()


def _ensure_tasks_phase7_columns() -> None:
    """Ensure Phase 7 columns exist on tasks table.

    Requirements:
    - project TEXT NOT NULL
    - type TEXT NOT NULL
    - description TEXT

    Safety:
    - Do not drop tables
    - Do not delete existing rows
    - Only ALTER TABLE when a column is missing
    """

    with get_connection() as conn:
        cur = conn.execute("PRAGMA table_info(tasks);")
        existing = {str(r[1]) for r in cur.fetchall()}

        # Note: SQLite requires a DEFAULT when adding a NOT NULL column to an existing table.
        # These defaults are only used when backfilling existing rows.
        if "project" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN project TEXT NOT NULL DEFAULT 'General'")
        if "type" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN type TEXT NOT NULL DEFAULT 'Task'")
        if "description" not in existing:
            conn.execute("ALTER TABLE tasks ADD COLUMN description TEXT")

        conn.commit()
