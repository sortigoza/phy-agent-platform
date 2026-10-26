"""The SQLite database: one file, raw sqlite3, named query functions.

`connect()` applies pending `migrations/NNN_<name>.sql` files in order, each in its own
transaction, tracked by `PRAGMA user_version`. A merged migration is never edited; there are no
down-migrations.
"""

import json
import re
import sqlite3
from datetime import UTC, date, datetime
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


def read_state(path: Path, key: str) -> str | None:
    """One state value, read-only and without migrating: for a command that may run from code
    newer than the Release that owns the database. None if the db or the table doesn't exist."""
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.OperationalError:
        return None
    try:
        row = conn.execute("SELECT value FROM state WHERE key = ?", (key,)).fetchone()
    except sqlite3.OperationalError:
        return None
    finally:
        conn.close()
    return row[0] if row else None


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
    arxiv_id: str | None = None,
) -> None:
    """The `runs` row of a Stage run with no model call (`ok` or `failed`)."""
    with conn:
        conn.execute(
            "INSERT INTO runs (id, stage, arxiv_id, status, error, started_at, ended_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?)",
            (run_id, stage, arxiv_id, status, error, started_at, _now()),
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


def draft_cards(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every draft Card with its Paper version's source type, oldest first (Verify's catch-up)."""
    return conn.execute(
        "SELECT cards.*, paper_versions.source_type FROM cards JOIN paper_versions"
        " USING (arxiv_id, version) WHERE cards.status = 'draft' ORDER BY cards.id"
    ).fetchall()


def latest_card(conn: sqlite3.Connection, arxiv_id: str) -> sqlite3.Row | None:
    """The Card of the Paper's latest Carded version, with its source type."""
    return conn.execute(
        "SELECT cards.*, paper_versions.source_type FROM cards JOIN paper_versions"
        " USING (arxiv_id, version) WHERE arxiv_id = ? ORDER BY version DESC LIMIT 1",
        (arxiv_id,),
    ).fetchone()


def write_verified_card(
    conn: sqlite3.Connection,
    card_id: int,
    card_json: str,
    unsupported_count: int,
    inferred_count: int,
    invented_numbers_json: str,
    warnings_json: str,
) -> None:
    """Store what Verify made of a Card. A draft (or re-verified) Card becomes `verified`; a
    reviewed or stale one keeps its status."""
    with conn:
        conn.execute(
            "UPDATE cards SET card_json = ?, unsupported_count = ?, inferred_count = ?,"
            " invented_numbers_json = ?, warnings_json = ?,"
            " status = CASE WHEN status IN ('draft', 'verified') THEN 'verified' ELSE status END,"
            " updated_at = ? WHERE id = ?",
            (
                card_json,
                unsupported_count,
                inferred_count,
                invented_numbers_json,
                warnings_json,
                _now(),
                card_id,
            ),
        )


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


def unscreened(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """The latest version of every Paper that has no screening, with the Paper's metadata.
    Older versions are never screened: `papers` holds only the latest title and abstract."""
    return conn.execute(
        "SELECT p.arxiv_id, p.latest_version AS version, p.title, p.abstract, p.categories,"
        " p.sets FROM papers p LEFT JOIN screenings s"
        " ON s.arxiv_id = p.arxiv_id AND s.version = p.latest_version"
        " WHERE s.arxiv_id IS NULL ORDER BY p.arxiv_id"
    ).fetchall()


def get_screening(conn: sqlite3.Connection, arxiv_id: str, version: int) -> sqlite3.Row | None:
    return conn.execute(
        "SELECT * FROM screenings WHERE arxiv_id = ? AND version = ?", (arxiv_id, version)
    ).fetchone()


def write_screening(
    conn: sqlite3.Connection,
    *,
    arxiv_id: str,
    version: int,
    prefilter: str,
    scores_json: str | None,
    best_score: float | None,
    screened_in: bool,
    model: str | None,
    prompt_version: str | None,
    run_id: str,
) -> None:
    """Store a Paper version's screening, replacing the one it has (`filter --force`)."""
    with conn:
        conn.execute(
            "INSERT OR REPLACE INTO screenings (arxiv_id, version, prefilter, scores_json,"
            " best_score, screened_in, model, prompt_version, run_id, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                arxiv_id,
                version,
                prefilter,
                scores_json,
                best_score,
                int(screened_in),
                model,
                prompt_version,
                run_id,
                _now(),
            ),
        )


def uncarded_screened_in(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Every Screened-in latest Paper version without a Card, as (arxiv_id, version, best_score)."""
    return conn.execute(
        "SELECT s.arxiv_id, s.version, s.best_score FROM screenings s"
        " JOIN papers p ON p.arxiv_id = s.arxiv_id AND p.latest_version = s.version"
        " LEFT JOIN cards c ON c.arxiv_id = s.arxiv_id AND c.version = s.version"
        " WHERE s.screened_in AND c.id IS NULL ORDER BY s.arxiv_id"
    ).fetchall()


def stale_cards(conn: sqlite3.Connection, *, relevant_only: bool) -> list[sqlite3.Row]:
    """The latest version of every Paper whose newest Card is Stale, as (arxiv_id, version,
    best_score); with `relevant_only`, only when that Card's latest Review is yes or partly."""
    return conn.execute(
        "SELECT p.arxiv_id, p.latest_version AS version, s.best_score FROM papers p"
        " JOIN cards c ON c.arxiv_id = p.arxiv_id AND c.version = ("
        "   SELECT max(version) FROM cards WHERE arxiv_id = p.arxiv_id)"
        " LEFT JOIN screenings s ON s.arxiv_id = p.arxiv_id AND s.version = p.latest_version"
        " WHERE c.status = 'stale' AND c.version < p.latest_version AND (:all OR ("
        "   SELECT relevance FROM reviews WHERE card_id = c.id"
        "   ORDER BY created_at DESC, id DESC LIMIT 1) IN ('yes', 'partly'))"
        " ORDER BY p.arxiv_id",
        {"all": not relevant_only},
    ).fetchall()


# A Card with what `/review` shows beside it: its Paper's metadata and best score.
REVIEW_CARD = (
    "SELECT c.*, p.title, p.authors, p.latest_version, pv.source_type, s.best_score,"
    " s.arxiv_id IS NULL AS unscreened FROM cards c JOIN papers p USING (arxiv_id)"
    " JOIN paper_versions pv USING (arxiv_id, version)"
    " LEFT JOIN screenings s ON s.arxiv_id = c.arxiv_id AND s.version = c.version"
)


def card_for_review(conn: sqlite3.Connection, card_id: int) -> sqlite3.Row | None:
    """One Card as `review_queue` returns it, whatever its status."""
    return conn.execute(REVIEW_CARD + " WHERE c.id = ?", (card_id,)).fetchone()


def get_review(conn: sqlite3.Connection, card_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM reviews WHERE card_id = ?", (card_id,)).fetchone()


def review_queue(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Cards awaiting a Review, next first, with their Paper's metadata and best score: verified
    or Stale Cards with no Review, except a Stale one whose Paper has a newer Card. Cards without
    a screening (`read --paper`) come first, then by `best_score` descending."""
    return conn.execute(
        REVIEW_CARD + " WHERE c.status IN ('verified', 'stale')"
        " AND NOT EXISTS (SELECT 1 FROM reviews WHERE card_id = c.id)"
        " AND (c.status = 'verified' OR NOT EXISTS (SELECT 1 FROM cards n"
        "   WHERE n.arxiv_id = c.arxiv_id AND n.version > c.version))"
        " ORDER BY unscreened DESC, s.best_score DESC NULLS LAST, c.id"
    ).fetchall()


def write_review(
    conn: sqlite3.Connection,
    card_id: int,
    relevance: Literal["yes", "partly", "no"],
    deep_read: bool,
    seconds_spent: int,
    note: str | None,
) -> bool:
    """Store a Card's Review and make a verified Card `reviewed`; a Stale Card stays Stale, so
    Read's selection can re-card it. A Card has at most one Review: returns False, writing
    nothing, if it has one already."""
    with conn:
        if get_review(conn, card_id):
            return False
        conn.execute(
            "INSERT INTO reviews (card_id, relevance, deep_read, seconds_spent, note, created_at)"
            " VALUES (?, ?, ?, ?, ?, ?)",
            (card_id, relevance, int(deep_read), seconds_spent, note, _now()),
        )
        conn.execute(
            "UPDATE cards SET status = 'reviewed', updated_at = ?"
            " WHERE id = ? AND status = 'verified'",
            (_now(), card_id),
        )
    return True


def add_flag(
    conn: sqlite3.Connection, card_id: int, field_path: str, kind: str, note: str | None
) -> int:
    with conn:
        row = conn.execute(
            "INSERT INTO flags (card_id, field_path, kind, note, created_at)"
            " VALUES (?, ?, ?, ?, ?) RETURNING id",
            (card_id, field_path, kind, note, _now()),
        ).fetchone()
    return row["id"]


def get_flag(conn: sqlite3.Connection, flag_id: int) -> sqlite3.Row | None:
    return conn.execute("SELECT * FROM flags WHERE id = ?", (flag_id,)).fetchone()


def delete_flag(conn: sqlite3.Connection, flag_id: int) -> None:
    with conn:
        conn.execute("DELETE FROM flags WHERE id = ?", (flag_id,))


def card_flags(conn: sqlite3.Connection, card_id: int) -> list[sqlite3.Row]:
    """A Card's Flags, oldest first."""
    return conn.execute("SELECT * FROM flags WHERE card_id = ? ORDER BY id", (card_id,)).fetchall()


def flags_since(conn: sqlite3.Connection, since: str) -> list[sqlite3.Row]:
    """The Flags created from `since` on, with their Card's Paper version, newest first."""
    return conn.execute(
        "SELECT f.*, c.arxiv_id, c.version FROM flags f JOIN cards c ON c.id = f.card_id"
        " WHERE f.created_at >= ? ORDER BY f.created_at DESC, f.id DESC",
        (since,),
    ).fetchall()


def cards_read_since(conn: sqlite3.Connection, day: date) -> list[sqlite3.Row]:
    """Cards per UTC day of the Read run that wrote them, from `day` on, as (day, cards)."""
    return conn.execute(
        "SELECT date(r.started_at) AS day, count(*) AS cards FROM cards c"
        " JOIN runs r ON r.id = c.run_id WHERE r.started_at >= ? GROUP BY day",
        (day.isoformat(),),
    ).fetchall()


def spend_since(conn: sqlite3.Connection, day: date) -> float:
    """What every run since the start of `day` (UTC) cost."""
    return conn.execute(
        "SELECT coalesce(sum(cost_usd), 0) FROM runs WHERE started_at >= ?", (day.isoformat(),)
    ).fetchone()[0]


def funnel(conn: sqlite3.Connection, since: str) -> dict[str, int]:
    """What happened at each step from `since` on (SPEC §9 funnel)."""
    row = conn.execute(
        "SELECT"
        " (SELECT count(*) FROM paper_versions WHERE first_seen_datestamp > date(:since))"
        "   AS harvested,"
        " (SELECT count(*) FROM screenings s JOIN runs r ON r.id = s.run_id"
        "   WHERE s.prefilter IN ('pass', 'skipped') AND r.started_at >= :since) AS candidates,"
        " (SELECT count(*) FROM screenings s JOIN runs r ON r.id = s.run_id"
        "   WHERE s.screened_in AND r.started_at >= :since) AS screened_in,"
        " (SELECT count(*) FROM cards c JOIN runs r ON r.id = c.run_id"
        "   WHERE r.started_at >= :since) AS carded,"
        " (SELECT count(*) FROM cards c JOIN runs r ON r.id = c.run_id"
        "   WHERE c.status IN ('verified', 'reviewed', 'stale') AND r.started_at >= :since)"
        "   AS verified,"
        " (SELECT count(*) FROM reviews WHERE created_at >= :since) AS reviewed,"
        " (SELECT count(*) FROM reviews WHERE relevance IN ('yes', 'partly')"
        "   AND created_at >= :since) AS relevant,"
        " (SELECT count(*) FROM reviews WHERE deep_read AND created_at >= :since) AS deep_read",
        {"since": since},
    ).fetchone()
    return dict(row)


def unretried_failures(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Failed runs with no later ok run of the same Stage (and Paper, for per-Paper runs),
    oldest first."""
    return conn.execute(
        "SELECT f.id, f.stage, f.arxiv_id, f.error, f.started_at FROM runs f"
        " WHERE f.status = 'failed' AND NOT EXISTS ("
        "   SELECT 1 FROM runs r WHERE r.stage = f.stage AND r.arxiv_id IS f.arxiv_id"
        "   AND r.status = 'ok' AND r.started_at > f.started_at)"
        " ORDER BY f.started_at, f.id"
    ).fetchall()


def list_runs(
    conn: sqlite3.Connection,
    *,
    stage: str | None = None,
    status: str | None = None,
    arxiv_ids: list[str] | None = None,
    since: str | None = None,
) -> list[sqlite3.Row]:
    """Runs for `/runs`, newest first; a filter left as None matches every run. `since` is an
    ISO timestamp (or date) compared with `started_at`."""
    return conn.execute(
        "SELECT * FROM runs WHERE (:stage IS NULL OR stage = :stage)"
        " AND (:status IS NULL OR status = :status)"
        " AND (:ids IS NULL OR arxiv_id IN (SELECT value FROM json_each(:ids)))"
        " AND (:since IS NULL OR started_at >= :since)"
        " ORDER BY started_at DESC, id DESC",
        {
            "stage": stage,
            "status": status,
            "ids": None if arxiv_ids is None else json.dumps(arxiv_ids),
            "since": since,
        },
    ).fetchall()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")
