"""The SQLite database: one file, raw sqlite3, named query functions.

`connect()` applies pending `migrations/NNN_<name>.sql` files in order, each in its own
transaction, tracked by `PRAGMA user_version`. A merged migration is never edited; there are no
down-migrations.
"""

import re
import sqlite3
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import structlog

log = structlog.get_logger()

MIGRATIONS = files("phy") / "migrations"
BUSY_TIMEOUT_MS = 10_000


def connect(path: Path, migrations=MIGRATIONS) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA foreign_keys = ON")
    _migrate(conn, migrations)
    return conn


def _migrate(conn: sqlite3.Connection, migrations) -> None:
    current = conn.execute("PRAGMA user_version").fetchone()[0]
    pending = sorted(
        (
            (int(m.group(1)), entry)
            for entry in migrations.iterdir()
            if (m := re.fullmatch(r"(\d{3})_\w+\.sql", entry.name))
        ),
        key=lambda pair: pair[0],
    )
    numbers = [number for number, _ in pending]
    if len(numbers) != len(set(numbers)):
        raise RuntimeError(f"two migrations share a number: {sorted(numbers)}")
    for number, entry in pending:
        if number <= current:
            continue
        try:
            conn.executescript(
                f"BEGIN;\n{entry.read_text()}\nPRAGMA user_version = {number};\nCOMMIT;"
            )
        except sqlite3.Error:
            conn.rollback()
            raise
        log.info("db.migrated", migration=entry.name)


def get_state(conn: sqlite3.Connection, key: str) -> str | None:
    row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else None


def set_state(conn: sqlite3.Connection, key: str, value: str) -> None:
    with conn:
        conn.execute(
            "INSERT INTO state (key, value, updated_at) VALUES (?, ?, ?) ON CONFLICT (key)"
            " DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (key, value, datetime.now(UTC).isoformat(timespec="seconds")),
        )
