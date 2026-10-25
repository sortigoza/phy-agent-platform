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
from typing import Literal

import structlog

from phy.arxiv import ArxivRecord

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
            (key, value, _now()),
        )


def delete_state(conn: sqlite3.Connection, key: str) -> None:
    with conn:
        conn.execute("DELETE FROM state WHERE key = ?", (key,))


def record_run(
    conn: sqlite3.Connection,
    run_id: str,
    stage: str,
    status: str,
    started_at: str,
    error: str | None = None,
) -> None:
    """The `runs` row of a Stage run with no model call (`ok` or `failed`)."""
    with conn:
        conn.execute(
            "INSERT INTO runs (id, stage, status, error, started_at, ended_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (run_id, stage, status, error, started_at, _now()),
        )


Upserted = Literal["new_paper", "new_version", "metadata_only", "unchanged"]


def upsert_paper(conn: sqlite3.Connection, record: ArxivRecord) -> Upserted:
    """Upsert a Paper and its versions from arXivRaw, as Watch does, and say which case it was.
    `sets` accumulates the sets a Paper was seen in. A version already known keeps its first
    datestamp and its source columns."""
    now = _now()
    metadata = {
        "title": record.title,
        "authors": record.authors,
        "abstract": record.abstract,
        "categories": " ".join(record.categories),
        "primary_category": record.primary_category,
        "license": record.license,
    }
    with conn:
        paper = get_paper(conn, record.arxiv_id)
        known = {
            row["version"]
            for row in conn.execute(
                "SELECT version FROM paper_versions WHERE arxiv_id = ?", (record.arxiv_id,)
            )
        }
        sets = paper["sets"].split() if paper else []
        sets += [s for s in record.sets if s not in sets]
        latest = max(record.latest_version, paper["latest_version"] if paper else 0)
        row = {**metadata, "latest_version": latest, "sets": " ".join(sets)}
        if paper is None:
            outcome = "new_paper"
        elif {v.number for v in record.versions} - known:
            outcome = "new_version"
        elif any(paper[k] != v for k, v in row.items()):
            outcome = "metadata_only"
        else:
            return "unchanged"
        conn.execute(
            "INSERT INTO papers (arxiv_id, latest_version, title, authors, abstract, categories,"
            " primary_category, license, sets, first_seen_at, updated_at)"
            " VALUES (:arxiv_id, :latest_version, :title, :authors, :abstract, :categories,"
            " :primary_category, :license, :sets, :now, :now) ON CONFLICT (arxiv_id) DO UPDATE SET"
            " latest_version = excluded.latest_version, title = excluded.title,"
            " authors = excluded.authors, abstract = excluded.abstract,"
            " categories = excluded.categories, primary_category = excluded.primary_category,"
            " license = excluded.license, sets = excluded.sets, updated_at = excluded.updated_at",
            {**row, "arxiv_id": record.arxiv_id, "now": now},
        )
        conn.executemany(
            "INSERT INTO paper_versions (arxiv_id, version, submitted_at, first_seen_datestamp)"
            " VALUES (?, ?, ?, ?) ON CONFLICT (arxiv_id, version) DO NOTHING",
            [
                (
                    record.arxiv_id,
                    v.number,
                    v.submitted_at.isoformat(),
                    record.datestamp.isoformat(),
                )
                for v in record.versions
            ],
        )
    return outcome


def mark_cards_stale(conn: sqlite3.Connection, arxiv_id: str, latest_version: int) -> int:
    """Make the Cards of older versions of a Paper Stale; returns how many changed."""
    # `cards` arrives with the Read call (migration 003_cards); before it there is nothing to do.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'cards'").fetchone():
        return 0
    with conn:
        return conn.execute(
            "UPDATE cards SET status = 'stale'"
            " WHERE arxiv_id = ? AND version < ? AND status != 'stale'",
            (arxiv_id, latest_version),
        ).rowcount


def get_paper(conn: sqlite3.Connection, arxiv_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM papers WHERE arxiv_id = ?", (arxiv_id,)).fetchone()


def get_paper_version(conn: sqlite3.Connection, arxiv_id: str, version: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM paper_versions WHERE arxiv_id = ? AND version = ?", (arxiv_id, version)
    ).fetchone()


def record_source(
    conn: sqlite3.Connection,
    arxiv_id: str,
    version: int,
    source_type: str,
    local_path: str,
    sha256: str,
) -> None:
    with conn:
        conn.execute(
            "UPDATE paper_versions SET source_type = ?, local_path = ?, sha256 = ?, fetched_at = ?"
            " WHERE arxiv_id = ? AND version = ?",
            (source_type, local_path, sha256, _now(), arxiv_id, version),
        )


def record_run_call(
    conn: sqlite3.Connection,
    *,
    run_id: str,
    stage: str,
    arxiv_id: str | None,
    model: str | None,
    prompt_version: str | None,
    ok: bool,
    error: str | None,
    tokens_in: int,
    tokens_out: int,
    cache_read_tokens: int,
    cache_write_tokens: int,
    cost_usd: float,
    started_at: str,
    ended_at: str,
    log_path: str,
) -> None:
    """Fold one model call into its run's row: tokens and cost add up, and one failed call
    makes the run failed."""
    with conn:
        conn.execute(
            "INSERT INTO runs (id, stage, arxiv_id, status, error, model, prompt_version,"
            " tokens_in, tokens_out, cache_read_tokens, cache_write_tokens, cost_usd, started_at,"
            " ended_at, log_path) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
            " ON CONFLICT (id) DO UPDATE SET"
            " status = CASE WHEN runs.status = 'failed' THEN 'failed' ELSE excluded.status END,"
            " error = coalesce(runs.error, excluded.error),"
            " tokens_in = runs.tokens_in + excluded.tokens_in,"
            " tokens_out = runs.tokens_out + excluded.tokens_out,"
            " cache_read_tokens = runs.cache_read_tokens + excluded.cache_read_tokens,"
            " cache_write_tokens = runs.cache_write_tokens + excluded.cache_write_tokens,"
            " cost_usd = runs.cost_usd + excluded.cost_usd, ended_at = excluded.ended_at",
            (
                run_id,
                stage,
                arxiv_id,
                "ok" if ok else "failed",
                error,
                model,
                prompt_version,
                tokens_in,
                tokens_out,
                cache_read_tokens,
                cache_write_tokens,
                cost_usd,
                started_at,
                ended_at,
                log_path,
            ),
        )


def get_run(conn: sqlite3.Connection, run_id: str) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()


def get_card(conn: sqlite3.Connection, arxiv_id: str, version: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM cards WHERE arxiv_id = ? AND version = ?", (arxiv_id, version)
    ).fetchone()


def write_draft_card(
    conn: sqlite3.Connection,
    arxiv_id: str,
    version: int,
    card_json: str,
    model: str,
    prompt_version: str,
    schema_version: str,
    run_id: str,
) -> int:
    """Store a draft Card, replacing the Paper version's Card if it has one (`read --force`):
    the row keeps its id and loses everything Verify had added."""
    now = _now()
    with conn:
        row = conn.execute(
            "INSERT INTO cards (arxiv_id, version, card_json, status, model, prompt_version,"
            " schema_version, run_id, created_at, updated_at)"
            " VALUES (?, ?, ?, 'draft', ?, ?, ?, ?, ?, ?) ON CONFLICT (arxiv_id, version)"
            " DO UPDATE SET card_json = excluded.card_json, status = 'draft',"
            " unsupported_count = NULL, inferred_count = NULL, invented_numbers_json = NULL,"
            " warnings_json = NULL, model = excluded.model,"
            " prompt_version = excluded.prompt_version,"
            " schema_version = excluded.schema_version, run_id = excluded.run_id,"
            " updated_at = excluded.updated_at RETURNING id",
            (arxiv_id, version, card_json, model, prompt_version, schema_version, run_id, now, now),
        ).fetchone()
    return row["id"]


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
